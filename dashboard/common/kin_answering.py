"""Apply the CEO's cached writing policy at the shared LLM boundary."""
POLICY_ID = 'ceo-directive:kin-answer-first-natural-link'


def apply_policy(prompt, slot):
    if slot != 'kin_pipeline' or not isinstance(prompt, str):
        return prompt
    policy, separator, evidence = prompt.partition('\nEVIDENCE_JSON:\n')
    if not separator or 'sources_by_article' not in policy or 'Return question_id' not in policy:
        return prompt
    from dashboard.agents.synapse import cached_index
    from pathlib import Path
    index = cached_index(Path(__file__).resolve().parents[2])
    directive = next((row for row in index.get('operatingDirectives', [])
                      if row.get('id') == POLICY_ID and row.get('active')), {})
    replacement = directive.get('promptPolicy')
    if not isinstance(replacement, str) or not 100 <= len(replacement) <= 10000:
        return prompt
    return replacement + separator + evidence
