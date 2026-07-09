def permission_feature_enabled(code):
    return True


def tool_feature_enabled(name):
    return True


def filter_feature_permissions(codes):
    return [code for code in (codes or []) if permission_feature_enabled(code)]


def filter_feature_tools(names):
    return [name for name in (names or []) if tool_feature_enabled(name)]
