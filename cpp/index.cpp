// Inverted index for the shopping agent's search_products tool.
//
// Why C++ here: search is on the agent's hot path (every tool call that searches
// products). Python's linear scan is O(n) per query over every product; this
// index makes tag lookups O(1) and substring name lookups O(candidates).
//
// Index strategy:
//   - tag index:    exact tag string -> product ids  (O(1) lookup)
//   - unigram index: single UTF-8 character -> product ids (narrows substring
//     candidates before a precise std::string::find)
//
// Built with pybind11 so tools.py can call it as `fast_index.ProductIndex`.

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <algorithm>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace py = pybind11;

// Split a UTF-8 string into its characters (a Chinese char is 3 bytes).
static std::vector<std::string> utf8_chars(const std::string& s) {
    std::vector<std::string> chars;
    size_t i = 0;
    while (i < s.size()) {
        size_t len = 1;
        unsigned char c = static_cast<unsigned char>(s[i]);
        if ((c & 0x80) == 0)        len = 1;  // ASCII
        else if ((c & 0xE0) == 0xC0) len = 2;
        else if ((c & 0xF0) == 0xE0) len = 3;  // CJK
        else if ((c & 0xF8) == 0xF0) len = 4;
        chars.push_back(s.substr(i, len));
        i += len;
    }
    return chars;
}

class ProductIndex {
public:
    std::vector<std::string> names;
    std::vector<double> prices;
    std::vector<std::vector<std::string>> tags;

    std::unordered_map<std::string, std::vector<int>> tag_index;      // tag -> ids
    std::unordered_map<std::string, std::vector<int>> unigram_index;  // char -> ids (from name)

    // Build the index from three parallel arrays.
    void build(const std::vector<std::string>& n,
               const std::vector<double>& p,
               const std::vector<std::vector<std::string>>& t) {
        names = n;
        prices = p;
        tags = t;
        tag_index.clear();
        unigram_index.clear();

        for (size_t i = 0; i < n.size(); i++) {
            // exact tag -> product id
            for (const auto& tag : tags[i]) {
                tag_index[tag].push_back(static_cast<int>(i));
            }
            // each unique character of the name -> product id
            std::unordered_set<std::string> seen;
            for (const auto& ch : utf8_chars(names[i])) {
                if (seen.insert(ch).second) {
                    unigram_index[ch].push_back(static_cast<int>(i));
                }
            }
        }
    }

    // Search products whose name/tags contain `keyword` and price <= max_price.
    std::vector<int> search(const std::string& keyword, double max_price) {
        std::vector<int> result;
        std::unordered_set<int> seen;

        auto add = [&](int id) {
            if (prices[id] <= max_price && seen.insert(id).second) {
                result.push_back(id);
            }
        };

        // 1. exact tag match via inverted index (O(1))
        auto it = tag_index.find(keyword);
        if (it != tag_index.end()) {
            for (int id : it->second) add(id);
        }

        // 2. substring match on name: narrow candidates via the first char's
        //    posting list, then verify with std::string::find.
        auto chars = utf8_chars(keyword);
        if (!chars.empty()) {
            auto first = unigram_index.find(chars[0]);
            if (first != unigram_index.end()) {
                for (int id : first->second) {
                    if (names[id].find(keyword) != std::string::npos) {
                        add(id);
                    }
                }
            }
        }

        std::sort(result.begin(), result.end());
        return result;
    }
};

PYBIND11_MODULE(fast_index, m) {
    m.doc() = "C++ inverted index for product search";
    py::class_<ProductIndex>(m, "ProductIndex")
        .def(py::init<>())
        .def("build", &ProductIndex::build)
        .def("search", &ProductIndex::search);
}
