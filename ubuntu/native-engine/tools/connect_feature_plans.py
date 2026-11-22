from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'tools/iq3_memory_ab.py';s=p.read_text(encoding='utf-8')
s=s.replace("    plan = parser.parse_args().plan", "    plan_argument.choices += ('qfuse-check','qfuse-abba','quality-qfuse-paired')\n    plan = parser.parse_args().plan\n    from feature_plans import feature_plan,feature_enabled,FEATURES\n    selected_feature=feature_plan(plan)")
s=s.replace('    for name, flags in arms:', '    if selected_feature:arms=selected_feature[1]\n    for name, flags in arms:')
s=s.replace("        arm['log'] =", "        if selected_feature:arm['env'][FEATURES[selected_feature[0]]]='1' if feature_enabled(name,selected_feature[0]) else '0'\n        arm['log'] =",1)
old="if plan in ('draft-it-abba','quality-draft-paired','head-profile','tsum-check','tsum-abba','quality-tsum-paired','profile-learn','profile-learn-abba','quality-profile-paired','pcie55-check','pcie55-abba','quality-pcie55-paired','pcie20-check','pcie20-abba','quality-pcie20-paired'):"
s=s.replace(old,old.replace('if plan in','if selected_feature or plan in'))
anchor="                    if plan == 'short-diagnostic':"
s=s.replace(anchor,"""                    if plan=='qfuse-abba':
                        command[command.index('--tokens')+1]='256'
                        command[command.index('--prompt-set')+1]='iq3-chunk-v1'
                        command+=['--warmup','5','--runs','5']
"""+anchor)
s=s.replace("('head-profile','tsum-check','pcie55-check','pcie20-check')", "('head-profile','tsum-check','pcie55-check','pcie20-check','qfuse-check')")
s=s.replace("('tsum-check','pcie55-check','pcie20-check')", "('tsum-check','pcie55-check','pcie20-check','qfuse-check')")
s=s.replace("'quality-pcie20-paired')", "'quality-pcie20-paired','quality-qfuse-paired')")
anchor="    elif plan in ('pcie55-abba','pcie20-abba'):"
s=s.replace(anchor,"""    elif plan=='qfuse-abba':
        from summarize_feature import summarize_abba
        summarize_abba(stamp,'qfuse')
    elif plan=='quality-qfuse-paired':
        from summarize_feature import summarize_quality
        summarize_quality(stamp,'qfuse')
"""+anchor)
p.write_text(s,encoding='utf-8')
