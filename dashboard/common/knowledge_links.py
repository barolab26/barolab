"""Materialize only role/account relationships explicitly stored on knowledge nodes."""
STAFF = {'jarvis':'팀장', 'publi':'퍼블리', 'radar':'레이더', 'trace':'트레이스', 'doctor':'닥터', 'patch':'패치'}


def connect_explicit_context(graph):
    nodes, edges = graph['nodes'], graph['edges']
    known = {(edge['source'], edge['target'], edge['type']) for edge in edges}
    added = []
    profiles = {node['account']:identity for identity,node in nodes.items()
                if node.get('type') == 'AccountProfile' and isinstance(node.get('account'), str) and node['account']}
    def connect(source, target, kind):
        key = (source,target,kind)
        if source != target and key not in known:
            edge = {'source':source,'target':target,'type':kind,'sourceField':'roles' if kind == 'applies_to_role' else 'account'}
            edges.append(edge);added.append(edge);known.add(key)
    for identity,node in list(nodes.items()):
        for role in node.get('roles', []) if isinstance(node.get('roles'), list) else []:
            if not isinstance(role,str) or role not in STAFF:continue
            target = 'staff:' + role
            nodes.setdefault(target, {'type':'Staff','roleId':role,'displayName':STAFF[role],'title':STAFF[role]})
            connect(identity,target,'applies_to_role')
        account = node.get('account')
        if isinstance(account,str) and account in profiles:
            connect(identity,profiles[account],'account_context')
    return added
