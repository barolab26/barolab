"""Conversation know-how is scoped candidate knowledge, never proof of success."""


def usable_knowhow(node):
    required = ('title', 'originalText', 'method', 'whenToUse', 'limits', 'recordedAt')
    return (node.get('type') == 'PracticalKnowHow' and node.get('active') is True
            and node.get('sourceType') == 'ceo_conversation' and node.get('optional') is True
            and node.get('causalClaim') is False and node.get('measurementStatus') == 'not_measured'
            and all(isinstance(node.get(key), str) and node[key].strip() for key in required)
            and isinstance(node.get('roles'), list) and bool(node['roles']))
