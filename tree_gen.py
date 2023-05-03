from config import *

authorities = {
    "H": "h",
    "HO": "h:1",
    "UH": "u@h",
    "UHO": "u@h:1",
}

endings = {
    "P": "/p",
    "PQ": "/p?q",
    "PQF": "/p?q#f",
    "PF": "/p#f",
    "": "",
    "Q": "?q",
    "QF": "?q#f",
    "F": "#f",
}

def _build_valid_tree() -> dict[str, str]:
    # Standard URIs
    start = "s://"
    start_key = "S"
    scheme_auth = {}
    for auth_key in authorities.keys():
        scheme_auth[start_key + auth_key] = start + authorities[auth_key]
    standard = {}
    for ending_key in endings.keys():
        for curr_key in scheme_auth.keys():
            standard[curr_key + ending_key] = scheme_auth[curr_key] + endings[ending_key]
    return standard

def _merge_possibilities(base: dict[str, str], appendings: dict[str, str]) -> dict[str, str]:
    merged = {}
    for base_key in base.keys():
        for appending_key in appendings.keys():
            merged[f"{base_key}{appending_key}"] = f"{base[base_key]}{appendings[appending_key]}"
    return merged

def _build_complete_tree() -> dict[str, str]:
    running_tree = {
        "": ""
    }
    running_tree = _merge_possibilities(running_tree, {"S": "s://",
                                                       "": ""})
    running_tree = _merge_possibilities(running_tree, {"U": "u@",
                                                       "": ""})
    running_tree = _merge_possibilities(running_tree, {"H": "h",
                                                       "": ""})
    running_tree = _merge_possibilities(running_tree, {"O": ":1",
                                                       "": ""})
    running_tree = _merge_possibilities(running_tree, {"P": "/p",
                                                       "": ""})
    running_tree = _merge_possibilities(running_tree, {"Q": "?q",
                                                       "": ""})
    running_tree = _merge_possibilities(running_tree, {"F": "#f",
                                                       "": ""})
    return running_tree

def _build_empty_tree() -> dict[str, str]:
    return {
        "": ""
    }



def gen_tree(tree_filename: str):
    if FUNDAMENTAL_TREE_SELECTION == 0:
        tree = _build_complete_tree()
    elif FUNDAMENTAL_TREE_SELECTION == 1:
        tree = _build_valid_tree()
    else:
        tree = _build_empty_tree()

    # Record Tree in file
    with open(tree_filename, "w") as tree_file:
        for key in tree.keys():
            tree_file.write(f"{key}={tree[key]}\n")

def main():
    gen_tree("tree.txt")

if __name__ == "__main__":
    main()