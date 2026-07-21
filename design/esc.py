import sys

for p in sys.argv[1:]:
    s = open(p, encoding='utf-8').read()
    out = ''.join(c if ord(c) < 128 else '\\u%04x' % ord(c) for c in s)
    open(p, 'w', encoding='utf-8', newline='').write(out)
    n = sum(1 for c in out if ord(c) > 127)
    print(p, 'remaining non-ascii:', n)
