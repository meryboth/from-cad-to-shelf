# Stage - Copy. The words of a piece, built from the product's own facts.
# Every line traces back to a fact in product.json: the node rearranges and shortens, it never adds a claim. The brand
# only lends its voice (how long a line runs, whether it ends in a full stop), never the content.
#   taglines  short lines made of the two strongest features, e.g. "One fixed lens. One optical viewfinder."
#   intro     two or three facts joined into a sentence
#   spec      the fact list itself, for the sheet
# A seed picks which facts go where, so the same product can yield a different set for another run.
#
# Usage: py pipeline/copy.py <product dir> <brand dir> [--seed N] [--out runs/<product>/copy.json]
import json
import os
import random
import re
import sys

STOP = re.compile(r'^(a|an|the)\s+', re.I)
SPLIT = re.compile(r',| with | and | plus ')


def phrases(facts):
    """Short noun phrases out of the facts, longest first: 'A ribbed control dial on the front' -> 'a ribbed control dial'."""
    out = []
    for fact in facts:
        if ':' in fact:      # a list, like "Two colorways: White and Signal Orange": not a phrase
            continue
        for part in SPLIT.split(fact):
            part = part.strip().rstrip('.')
            if not part or len(part.split()) > 6:
                continue
            part = re.sub(r'\s+on the (front|back|side|right side|left side)$', '', part, flags=re.I)
            if part and part.lower() not in (p.lower() for p in out):
                out.append(part)
    return out


def capitalise(s):
    return s[:1].upper() + s[1:]


def taglines(facts, spec, rng, n=3):
    """Pairs of features, as two short sentences."""
    feats = [STOP.sub('', p) for p in phrases(facts)]
    feats = [f for f in feats if 2 <= len(f.split()) <= 5]
    rng.shuffle(feats)
    out = []
    for i in range(0, min(len(feats) - 1, n * 2), 2):
        out.append(f'{capitalise(feats[i])}. {capitalise(feats[i + 1])}.')
    colorways = list(spec.get('colorways', {}))
    if colorways:
        out.append(f"{capitalise(spec.get('category', 'product'))}. {len(colorways)} colorways.")
    return out[:n + 1] or [capitalise(spec.get('category', 'product')) + '.']



def lower_first(s):
    keep = s[:2].isalpha() and s[:2].isupper()  # an acronym like LCD stays as it is
    return s if keep else s[:1].lower() + s[1:]


def intro(facts, spec, rng):
    """The first fact as one sentence, then two more joined into a second one."""
    keep = [f.rstrip('.') for f in facts if ':' not in f]
    if not keep:
        return ''
    head, rest = keep[0], keep[1:]
    rng.shuffle(rest)
    rest = [lower_first(r) for r in rest[:2]]
    out = capitalise(head) + '.'
    if rest:
        out += ' ' + capitalise(rest[0]) + ('' if len(rest) == 1 else f', and {rest[1]}') + '.'
    colorways = list(spec.get('colorways', {}))
    if colorways:
        out += f" In {' and '.join(c.replace('-', ' ').title() for c in colorways)}."
    return out


def build(product, brand_dir, seed=7):
    spec = json.load(open(os.path.join(product, 'product.json'), encoding='utf-8'))
    facts = spec.get('facts', [])
    rng = random.Random(seed)
    return {'product': spec['name'], 'from': 'product.json facts', 'seed': seed,
            'taglines': taglines(facts, spec, rng), 'intro': intro(facts, spec, rng), 'facts': facts}


if __name__ == '__main__':
    args = sys.argv[1:]
    opt = lambda k, d=None: args[args.index(k) + 1] if k in args else d
    product, brand_dir = args[0], args[1]
    copy = build(product, brand_dir, int(opt('--seed', 7)))
    out = opt('--out')
    if out:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        json.dump(copy, open(out, 'w', encoding='utf-8'), indent=2)
    print(json.dumps(copy, indent=2, ensure_ascii=False))
