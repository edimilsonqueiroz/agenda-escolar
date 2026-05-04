import os

def fix_cp1252_double_encoded(text):
    """
    Reverse cp1252 double-encoding remaining in the text.
    After the previous byte-level fix, Portuguese chars (0xC0-0xFF) are correct.
    Remaining: chars whose original UTF-8 bytes were in 0x80-0xBF range got
    encoded via cp1252 into multi-byte UTF-8 sequences (e.g. 0x86 -> † -> E2 80 A0).
    Strategy: for each char C, get its cp1252 byte B. If B >= 0xC2 and forms a
    valid UTF-8 sequence with subsequent chars' cp1252 bytes, replace with decoded char.
    This safely handles all 2/3/4-byte UTF-8 original sequences.
    """
    # Build cp1252 reverse map: unicode char -> byte value (for 0x80-0xFF range)
    cp1252_rev = {}
    for b in range(0x80, 0x100):
        try:
            c = bytes([b]).decode('cp1252')
            cp1252_rev[c] = b
        except (UnicodeDecodeError, ValueError):
            pass

    def cp1252_byte(c):
        if ord(c) < 0x80:
            return ord(c)
        return cp1252_rev.get(c, None)

    result = []
    i = 0
    while i < len(text):
        c = text[i]
        b = cp1252_byte(c)

        if b is None or b < 0xC2:
            result.append(c)
            i += 1
            continue

        # Try 4-byte sequence (F0-F7)
        if 0xF0 <= b <= 0xF7 and i + 3 < len(text):
            b2 = cp1252_byte(text[i+1])
            b3 = cp1252_byte(text[i+2])
            b4 = cp1252_byte(text[i+3])
            if (b2 is not None and 0x80 <= b2 <= 0xBF and
                    b3 is not None and 0x80 <= b3 <= 0xBF and
                    b4 is not None and 0x80 <= b4 <= 0xBF):
                try:
                    decoded = bytes([b, b2, b3, b4]).decode('utf-8')
                    result.append(decoded)
                    i += 4
                    continue
                except UnicodeDecodeError:
                    pass

        # Try 3-byte sequence (E0-EF)
        if 0xE0 <= b <= 0xEF and i + 2 < len(text):
            b2 = cp1252_byte(text[i+1])
            b3 = cp1252_byte(text[i+2])
            if (b2 is not None and 0x80 <= b2 <= 0xBF and
                    b3 is not None and 0x80 <= b3 <= 0xBF):
                try:
                    decoded = bytes([b, b2, b3]).decode('utf-8')
                    result.append(decoded)
                    i += 3
                    continue
                except UnicodeDecodeError:
                    pass

        # Try 2-byte sequence (C2-DF) - these should already be fixed, but just in case
        if 0xC2 <= b <= 0xDF and i + 1 < len(text):
            b2 = cp1252_byte(text[i+1])
            if b2 is not None and 0x80 <= b2 <= 0xBF:
                try:
                    decoded = bytes([b, b2]).decode('utf-8')
                    result.append(decoded)
                    i += 2
                    continue
                except UnicodeDecodeError:
                    pass

        result.append(c)
        i += 1

    return ''.join(result)


templates_dir = 'app/templates'
fixed = []

for root, dirs, files in os.walk(templates_dir):
    for fname in files:
        if not fname.endswith('.html'):
            continue
        path = os.path.join(root, fname)
        with open(path, encoding='utf-8') as f:
            text = f.read()
        fixed_text = fix_cp1252_double_encoded(text)
        if fixed_text != text:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(fixed_text)
            fixed.append(os.path.relpath(path, templates_dir))

print('Fixed:', fixed if fixed else 'none')

# Verify
path = 'app/templates/teacher/submissions.html'
with open(path, encoding='utf-8') as f:
    text = f.read()
for kw in ['Voltar', 'Aprovar', 'Devolver', 'Aprovado', 'Submiss', 'avalia', 'Grupos']:
    idx = text.find(kw)
    if idx >= 0:
        print(f'{kw}: {repr(text[max(0,idx-6):idx+len(kw)])}')
