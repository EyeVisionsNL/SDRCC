from pathlib import Path

ROOT = Path('/home/eyevisions/SDRCC')
index = (ROOT / 'dashboard/templates/index.html').read_text(encoding='utf-8')
radio = (ROOT / 'dashboard/static/js/radio.js').read_text(encoding='utf-8')

checks = [
    ('legacy foundation status removed from template', 'Configuratie actief · services worden in v0.47.1a niet gewijzigd.' not in index),
    ('legacy foundation status removed from JavaScript', 'Configuratie actief · services worden in v0.47.1a niet gewijzigd.' not in radio),
    ('result element retained for save and error feedback', 'id="assignment-policy-result"' in index),
    ('result element hidden by default', 'id="assignment-policy-result" class="muted" hidden' in index),
    ('runtime context panel retained', 'id="assignment-policy-runtime"' in index),
    ('mission assignments retained', 'id="mission-assignments-form"' in index),
    ('receiver defaults retained', 'id="receiver-defaults-form"' in index),
    ('result clear helper present', 'function clearAssignmentPolicyResult()' in radio),
    ('successful context refresh clears stale text', 'clearAssignmentPolicyResult();' in radio),
    ('save feedback remains supported', 'if (result) result.textContent' in radio),
    ('context error feedback remains supported', 'Context laden mislukt:' in radio),
]

failed = False
for label, ok in checks:
    print(('PASS' if ok else 'FAIL') + ': ' + label)
    failed |= not ok

if index.count('id="assignment-policy-result"') != 1:
    print('FAIL: assignment-policy-result must occur exactly once')
    failed = True
else:
    print('PASS: assignment-policy-result is unique')

if failed:
    raise SystemExit(1)
print('VALIDATION PASS: v0.47.1d Assignment Status Polish')
