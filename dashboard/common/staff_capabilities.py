"""Shared staff ownership and capability contracts; host validators keep write gates."""
ACTION_OWNERS = {
    'recover_project_runtime':'patch', 'recover_project_work':'publi',
    'repair_kin_submission':'patch', 'run_cf_domain':'publi',
    'prepare_cf_source_fact':'publi', 'verify_cf_source_fact_fix':'patch',
    'repair_cf_known_failure':'patch',
}


def action_owner(tool, args):
    if not isinstance(tool,str) or not isinstance(args,dict):raise ValueError('Invalid tool ownership request')
    if tool == 'run_project_cycle':return 'doctor' if args.get('project') == 'legacy_remodel' else 'publi'
    if tool == 'advance_project_recovery':
        if set(args)!={'task_id','plan_sha256'}:raise ValueError('Recovery requires its task and exact plan binding')
        from common.repair_workflow import recovery_expected_actor
        return recovery_expected_actor(args['task_id'], args['plan_sha256'])
    return ACTION_OWNERS.get(tool)


def canonical_action(action):
    if not isinstance(action,dict) or set(action) != {'agent','tool','args'} or not isinstance(action['args'],dict):
        raise ValueError('Invalid action fields')
    owner=action_owner(action['tool'],action['args'])
    if owner is None:raise ValueError('No registered owner for this write tool')
    return {**action,'agent':owner}


def capability_catalog():
    from common.project_autonomy import COMMANDS
    from common.runtime_recovery import UNITS
    return [
        {'tool':'browser_ego_action','owner':'patch','args':['port','url','goal'],'permission':'repair','verification':'EGO screenshot/action receipt and fresh screen observation; submission uses existing verification'},
        {'tool':'read_source','owner':'current actor','args':['path','line?','lines?'],'limits':{'linesMaximum':240},'pagination':['sha256','totalLines','truncated','nextLine'],'verification':'follow nextLine for complete evidence'},
        {'tool':'run_project_cycle','owner':'publi (legacy_remodel: doctor)','args':['project'],'projects':list(COMMANDS),'permission':'execute','verification':'actual publication/reservation receipt; queued is not completed'},
        {'tool':'recover_project_runtime','owner':ACTION_OWNERS['recover_project_runtime'],'args':['project'],'projects':list(UNITS),'permission':'repair','whenToUse':'Registered scheduler or worker runtime is unavailable; prefer this bounded recovery before source-code investigation. A content hold is not a runtime error.','verification':'fresh source and symptom recheck; timer start alone is not recovery'},
        {'tool':'recover_project_work','owner':ACTION_OWNERS['recover_project_work'],'args':['project','work_id'],'projects':['cf_blog','naver_blog'],'permission':'repair','whenToUse':'Existing supported recovery of the same pre-submission failed work; preserve the approved document and verification. If held or submission is uncertain, reconcile first and use another independent eligible task.','verification':'same approved work, existing submission fences and actual completion receipt'},
        {'tool':'repair_kin_submission','owner':ACTION_OWNERS['repair_kin_submission'],'args':['account','question_id'],'permission':'repair','verification':'existing task-owned editor and submission evidence; never bypass quota/captcha'},
        {'tool':'advance_project_recovery','owner':'read recovery assignedAgent; host resolves current phase','args':['task_id','plan_sha256'],'permission':'repair','verification':'phase receipt is not entire recovery; re-read plan and symptom'},
        {'tool':'search_source','owner':'current actor','args':['query'],'availability':'Python standard library, bounded fixed-string source search'},
        {'tool':'evidence','owner':'current actor','args':['name','select?','fields?','offset?','limit?'],'limits':{'fieldMaximum':16,'pageMaximum':240},'availability':'named sanitized ledgers; conference, incident and recovery identifiers are separate'},
        {'tool':'propose_patch','owner':'patch','args':['files','test_files','objective'],'permission':'repair','verification':'candidate only; independent tests/review/apply/resume/verify remain in registered recovery workflow'},
        {'tool':'prepare_recovery','owner':'host','args':['project'],'permission':'repair','verification':'requires an exact current incident bound to an original terminal operation; then advance registered phases'},
    ]
