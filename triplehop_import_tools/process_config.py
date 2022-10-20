import copy
import json
import os
import re
import typing
import uuid

RE_FIELD_CONVERSION = re.compile(
    (
        # zero, one or multiple (inverse) relations
        r"(?:[$]ri?_[a-z_]+->)*"
        # zero or one (inverse) relations; dot for relation property and arrow for entity property
        r"(?:[$]ri?_[a-z_]+(?:[.]|->)){0,1}"
        # one property (entity or relation)
        r"[$](?:[a-z_]+)"
    )
)


def find_replacement(
    project_config: dict, er: str, current_ers: typing.List[str], to_replace: str
) -> typing.List[str]:
    path = [p.replace("$", "") for p in to_replace.split("->")]
    results = []
    new_paths = [[current_er, []] for current_er in current_ers]
    for i, p in enumerate(path):
        for (current_er, new_path) in new_paths:
            # not last element => p = relation => travel
            if i != len(path) - 1:
                (direction, relation_name) = p.split("_", 1)
                if direction == "r":
                    current_ers = project_config["relations_base"][relation_name][
                        "range"
                    ]
                else:
                    current_ers = project_config["relations_base"][relation_name][
                        "domain"
                    ]
                new_path.append(
                    f'${direction}_{project_config["relations_base"][relation_name]["id"]}'
                )
                new_paths = [
                    [current_er, new_path.copy()] for current_er in current_ers
                ]
                break
            # last element => p = relation.r_prop or e_prop
            # relation property
            if "." in p:
                (rel_type_id, r_prop) = p.split(".")
                (direction, relation_name) = rel_type_id.split("_", 1)
                new_path.append(
                    f'${direction}_{project_config["relations_base"][relation_name]["id"]}'
                )
                results.append(
                    f'{"->".join(new_path)}.${project_config["relation"][relation_name]["lookup"][r_prop]}'
                )
            # base -> relation
            elif p.split("_")[0] in ["r", "ri"]:
                (direction, relation_name) = p.split("_", 1)
                new_path.append(
                    f'${direction}_{project_config["relations_base"][relation_name]["id"]}'
                )
                results.append(f'{"->".join(new_path)}')
            # entity display name
            elif p == "display_name":
                new_path.append("$display_name")
                results.append(f'{"->".join(new_path)}')
            # entity property
            # Verify if the requested property exists for the current entity
            elif p in project_config[er][current_er]["lookup"]:
                new_path.append(f'${project_config[er][current_er]["lookup"][p]}')
                results.append(f'{"->".join(new_path)}')
            # If the property doesn't exist: don't add to results
    return results


def replace(project_config: dict, er: str, er_name: str, input: str) -> str:
    replacements = {}
    replacements_order = []
    for match in RE_FIELD_CONVERSION.finditer(input):
        if not match:
            continue

        to_replace = match.group(0)
        replacements_order.append(to_replace)

        if to_replace not in replacements:
            replacements[to_replace] = find_replacement(
                project_config, er, [er_name], to_replace
            )
    results = [input]
    for to_replace in replacements_order:
        new_results = []
        for result in results:
            new_results.extend(
                [
                    result.replace(to_replace, replacement, 1)
                    for replacement in replacements[to_replace]
                ]
            )
        results = new_results.copy()

    return " $||$ ".join(results)

    return result


def replace_group(project_config: dict, name: str) -> str:
    project_name, group_name = name.split(".")
    return project_config["groups_base"][project_name][group_name]["id"]


def process() -> None:
    project_config: typing.Dict[str, typing.Dict] = {
        "entity": {},
        "relation": {},
    }
    # Load relation config: ids, domains and ranges might be needed when replacing
    if os.path.exists(f"human_readable_config/relations.json"):
        with open(f"human_readable_config/relations.json") as f:
            project_config["relations_base"] = json.load(f)
    else:
        print("Please process config again after generating relation config.")
    # Load group config: ids might be needed when replacing
    if os.path.exists(f"human_readable_config/groups.json"):
        with open(f"human_readable_config/groups.json") as f:
            project_config["groups_base"] = json.load(f)
    # first iteration: detail, source, data
    for er in ["entity", "relation"]:
        for fn in os.listdir(f"human_readable_config/{er}"):
            name = fn.split(".")[0]
            project_config[er][name] = {}
            prev_field_lookup = {}
            with open(f"human_readable_config/{er}/{fn}") as f:
                config = json.load(f)
            # Store previously used uuids so they don't change
            if os.path.exists(f"config/{er}/{fn}"):
                with open(f"config/{er}/{fn}") as f:
                    prev_config = json.load(f)
                    if "data" in prev_config and "fields" in prev_config["data"]:
                        for field in prev_config["data"]["fields"]:
                            prev_field_lookup[
                                prev_config["data"]["fields"][field]["system_name"]
                            ] = field
            if "detail" in config:
                project_config[er][name]["detail"] = config["detail"]
            if "source" in config:
                project_config[er][name]["source"] = config["source"]
            if "data" in config:
                project_config[er][name]["data"] = {
                    "fields": {},
                    "permissions": {},
                }
                project_config[er][name]["lookup"] = {
                    "id": "id",
                }
                if "fields" in config["data"]:
                    for field in config["data"]["fields"]:
                        if field["system_name"] in prev_field_lookup:
                            id = prev_field_lookup[field["system_name"]]
                        else:
                            id = str(uuid.uuid4())
                        if "permissions" in field:
                            for permission, groups in field["permissions"].items():
                                field["permissions"][permission] = [
                                    replace_group(project_config, group)
                                    for group in groups
                                ]
                        project_config[er][name]["data"]["fields"][id] = field
                        project_config[er][name]["lookup"][field["system_name"]] = id
                if "permissions" in config["data"]:
                    for permission, groups in config["data"]["permissions"].items():
                        project_config[er][name]["data"]["permissions"][permission] = [
                            replace_group(project_config, group) for group in groups
                        ]

    if "relations_base" in project_config:
        # second iteraton: display, edit
        for er in ["entity", "relation"]:
            for fn in os.listdir(f"human_readable_config/{er}"):
                name = fn.split(".")[0]
                with open(f"human_readable_config/{er}/{fn}") as f:
                    config = json.load(f)
                if "display" in config:
                    project_config[er][name]["display"] = copy.deepcopy(
                        config["display"]
                    )
                    display = project_config[er][name]["display"]
                    if "title" in display:
                        display["title"] = replace(
                            project_config, er, name, display["title"]
                        )
                    if "layout" in display:
                        # TODO: add uuid to layout?
                        for layout in display["layout"]:
                            if "label" in layout:
                                layout["label"] = replace(
                                    project_config, er, name, layout["label"]
                                )
                            if "fields" in layout:
                                for field in layout["fields"]:
                                    field["field"] = replace(
                                        project_config, er, name, field["field"]
                                    )
                if "edit" in config:
                    project_config[er][name]["edit"] = copy.deepcopy(config["edit"])
                    edit = project_config[er][name]["edit"]
                    if "layout" in edit:
                        for layout in edit["layout"]:
                            if "label" in layout:
                                layout["label"] = replace(
                                    project_config, er, name, layout["label"]
                                )
                            if "fields" in layout:
                                for field in layout["fields"]:
                                    field["field"] = replace(
                                        project_config, er, name, field["field"]
                                    )

        # third iteration: es_data, es_display
        for er in ["entity", "relation"]:
            for fn in os.listdir(f"human_readable_config/{er}"):
                name = fn.split(".")[0]
                with open(f"human_readable_config/{er}/{fn}") as f:
                    config = json.load(f)
                if "es_data" in config:
                    project_config[er][name]["es_data"] = copy.deepcopy(
                        config["es_data"]
                    )
                    es_data = project_config[er][name]["es_data"]
                    if "fields" in es_data:
                        for field in es_data["fields"]:
                            if field["type"] == "nested":
                                field["base"] = replace(
                                    project_config, er, name, field["base"]
                                )
                                for part in field["parts"].values():
                                    part["selector_value"] = replace(
                                        project_config, er, name, part["selector_value"]
                                    )
                            elif field["type"] == "edtf_interval":
                                field["start"] = replace(
                                    project_config, er, name, field["start"]
                                )
                                field["end"] = replace(
                                    project_config, er, name, field["end"]
                                )
                            else:
                                field["selector_value"] = replace(
                                    project_config, er, name, field["selector_value"]
                                )
                            if "filter" in field:
                                field["filter"] = replace(
                                    project_config, er, name, field["filter"]
                                )
                    if "permissions" in es_data:
                        for permission, groups in es_data["permissions"].items():
                            es_data["permissions"][permission] = [
                                replace_group(project_config, group) for group in groups
                            ]
                if "es_display" in config:
                    project_config[er][name]["es_display"] = copy.deepcopy(
                        config["es_display"]
                    )

    # write out config
    for er in ["entity", "relation"]:
        if not os.path.exists(f"config/{er}"):
            os.makedirs(f"config/{er}")
        for name in project_config[er]:
            with open(f"config/{er}/{name}.json", "w") as f:
                config = {}
                for conf in [
                    "detail",
                    "source",
                    "data",
                    "display",
                    "edit",
                    "es_data",
                    "es_display",
                ]:
                    if conf in project_config[er][name]:
                        config[conf] = project_config[er][name][conf]
                json.dump(config, f, indent=4)


if __name__ == "__main__":
    process()
