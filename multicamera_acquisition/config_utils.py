def recursive_update(old_dict, updates):
    """Recursively update a dictionary with another dictionary.

    Parameters
    ----------
    old_dict : dict
        The dictionary to be updated.
    updates : dict
        The dictionary containing the updates.

    """
    for key, value in updates.items():
        if (
            key in old_dict
            and isinstance(old_dict[key], dict)
            and isinstance(value, dict)
        ):
            # If both config and updates have this key as a dictionary, recurse
            recursive_update(old_dict[key], value)
        else:
            # Otherwise, update the value directly
            old_dict[key] = value


def dict_update_with_precedence(*args):
    """Update a series of dictionaries, in decreasing order of precedence.

    Parameters
    ----------
    *args : dict
        The dictionaries to be updated, in decreasing order of precedence.

    Returns
    -------
    final_config : dict
        The final, updated dictionary.

    Examples:
    ---------
    >>> hard_coded_defaults = {'my_forgotten_param': {"got it?": "got it!"}, 'key1': 'default1', 'key2': 'default2'}
    >>> yaml_file_config = {'key2': 'yaml2', 'key3': 'yaml3'}
    >>> runtime_kwargs = {'key3': 'runtime3', 'key4': 'runtime4'}
    >>> final_config = dict_update_with_precedence(runtime_kwargs, yaml_file_config, hard_coded_defaults)
    >>> print(final_config)
    # {'my_forgotten_param': {'got it?': 'got it!'}, 'key1': 'default1', 'key2': 'yaml2', 'key3': 'runtime3', 'key4': 'runtime4'}

    """
    # Start with an empty dict
    final_config = {}

    # Add values from the arguments in reverse order, i.e. starting with the lowest precedence
    for config_dict in reversed(args):
        recursive_update(final_config, config_dict)

    return final_config
