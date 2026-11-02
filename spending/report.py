"""Render one month's report as a self-contained HTML page (inline SVG charts)."""
from __future__ import annotations

import html
from datetime import date

from .analyze import month_bounds

# Categories that count as eating and drinking out.
EAT_OUT = {"Fast food", "Restaurants and bars", "Delivery", "Alcohol"}


def money(v: float, cents: bool = False) -> str:
    sign = "-" if v < 0 else ""
    return f"{sign}${abs(v):,.2f}" if cents else f"{sign}${abs(v):,.0f}"


def signed(v: float) -> str:
    return ("+" if v > 0 else "-" if v < 0 else "±") + f"${abs(v):,.0f}"


def month_name(key: str, short: bool = False) -> str:
    s, _ = month_bounds(key)
    return s.strftime("%b" if short else "%B %Y")


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def _avg(vals):
    vals = list(vals)
    return sum(vals) / len(vals) if vals else 0.0


def build(summary: dict, month: str, history: int = 12) -> str:
    months = summary["months"]
    keys = [k for k in sorted(months) if k <= month]
    complete = [k for k in keys if months[k]["complete"]]
    cur = months[month]
    prior = [k for k in complete if k < month]
    prev_key = prior[-1] if prior else None
    # Compare only with months on the same pay: if pay changed recently, the
    # average starts at the change.
    changes = sorted(p["month"] for p in summary.get("pay_changes", []) if p["month"] <= month)
    since = changes[-1] if changes else ""
    same_pay = [k for k in prior if k >= since]
    base_keys = (same_pay or prior)[-3:]
    trend_keys = complete[-history:] if month in complete else (complete + [month])[-history:]
    rlabel = summary.get("retirement_label", "Retirement")
    if summary.get("retirement_estimate"):
        rlabel += " (estimate)"

    def base(field):
        return _avg(months[k][field] for k in base_keys) if base_keys else None

    # ---------------------------------------------------------------- stat tiles
    tiles = []
    for label, field, good_when_up in (
        ("Money in", "income_total", True),
        ("Rent", "rent", False),
        ("Everyday spending", "everyday_total", False),
        ("Saved", "saved_total" if cur.get("retirement") else "saved", True),
    ):
        v = cur[field]
        b = base(field)
        delta = ""
        if b is not None:
            d = v - b
            cls = "flat" if abs(d) < 25 else ("good" if (d > 0) == good_when_up else "bad")
            arrow = "▲" if d > 0 else "▼" if d < 0 else "●"
            delta = (f'<div class="delta {cls}"><span aria-hidden="true">{arrow}</span> '
                     f'{signed(d)} vs your {len(base_keys)}-month average</div>')
        extra = ""
        if field.startswith("saved") and cur["savings_rate"] is not None:
            if cur.get("retirement"):
                extra = (f'<div class="sub">{money(cur["saved"])} in the bank + {money(cur["retirement"])} '
                         f'to your {esc(rlabel)}. {cur["savings_rate"] * 100:.0f}% of your pay</div>')
            else:
                extra = f'<div class="sub">{cur["savings_rate"] * 100:.0f}% of what came in</div>'
        tiles.append(f'<div class="tile"><div class="label">{label}</div>'
                     f'<div class="value">{money(v)}</div>{extra}{delta}</div>')

    # ---------------------------------------------------------------- headline sentences
    lines = []
    if base_keys:
        d_every = cur["everyday_total"] - base("everyday_total")
        lines.append(
            f"Everyday spending was <b>{money(cur['everyday_total'])}</b>, "
            f"{'up' if d_every > 0 else 'down'} <b>{money(abs(d_every))}</b> from your "
            f"average for {month_name(base_keys[0], True)} to {month_name(base_keys[-1], True)}.")
    if since:
        rate_of = lambda ks: _avg(months[k]["savings_rate"] for k in ks if months[k]["savings_rate"] is not None)
        before = [k for k in complete if k < since]
        after = [k for k in complete if since <= k <= month]
        note = next((p.get("note", "") for p in summary["pay_changes"] if p["month"] == since), "")
        if before and after:
            lines.append(
                f"Your pay went up in {month_name(since, True)}"
                + (f" ({esc(note)})" if note else "")
                + f". Since then you've saved <b>{rate_of(after) * 100:.0f}%</b> of your pay on average, "
                f"compared with {rate_of(before) * 100:.0f}% before.")
        if same_pay and base_keys != prior[-3:]:
            lines.append(f"Averages only use months since the pay change, so they compare like with like.")
    eat = sum(v for c, v in cur["everyday"].items() if c in EAT_OUT)
    if eat:
        share = eat / cur["everyday_total"] * 100 if cur["everyday_total"] else 0
        lines.append(f"Eating and drinking out was <b>{money(eat)}</b>, {share:.0f}% of everyday spending.")
    chip = next((p for p in cur["top_places"] if p[0] == "Chipotle"), None)
    if chip:
        lines.append(f"Chipotle: <b>{chip[2]} visits</b> for {money(chip[1])}.")
    if cur["one_off_total"]:
        lines.append(f"One-offs kept out of everyday spending: <b>{money(cur['one_off_total'])}</b> "
                     f"({', '.join(esc(c) for c in cur['one_offs'])}).")

    # ---------------------------------------------------------------- charts
    trend_svg = _stacked_months(months, trend_keys, month, changes)
    saved_svg = _saved_bars(months, trend_keys, month, changes, rlabel)
    cats = sorted(set(cur["everyday"]) | {c for k in base_keys for c in months[k]["everyday"]})
    diffs = []
    for c in cats:
        now = cur["everyday"].get(c, 0.0)
        avg = _avg(months[k]["everyday"].get(c, 0.0) for k in base_keys) if base_keys else 0.0
        prev = months[prev_key]["everyday"].get(c, 0.0) if prev_key else 0.0
        diffs.append((c, now, prev, avg, now - avg))
    diffs.sort(key=lambda x: -x[1])
    change_svg = _diverging(sorted(diffs, key=lambda x: -abs(x[4]))[:10]) if base_keys else ""

    # ---------------------------------------------------------------- tables
    cat_rows = "".join(
        f"<tr><td>{esc(c)}{' <span class=tag>eating out</span>' if c in EAT_OUT else ''}</td>"
        f"<td class=n>{money(now)}</td><td class=n>{money(prev) if prev_key else '–'}</td>"
        f"<td class=n>{money(avg) if base_keys else '–'}</td>"
        f"<td class='n {'up' if d > 25 else 'down' if d < -25 else ''}'>{signed(d) if base_keys else '–'}</td></tr>"
        for c, now, prev, avg, d in diffs)
    places = "".join(f"<tr><td>{esc(n)}</td><td class=n>{cnt}</td><td class=n>{money(v)}</td></tr>"
                     for n, v, cnt in cur["top_places"])
    big = "".join(f"<tr><td class=d>{_d(i['date'])}</td><td>{esc(i['merchant'])}</td><td>{esc(i['category'])}</td>"
                  f"<td class=n>{money(i['amount'], True)}</td></tr>" for i in cur["big_purchases"])
    oneoff = "".join(f"<tr><td class=d>{_d(i['date'])}</td><td>{esc(i['merchant'])}</td><td>{esc(i['category'])}"
                     f"{'<div class=note>' + esc(i['note']) + '</div>' if i['note'] else ''}</td>"
                     f"<td class=n>{money(i['amount'], True)}</td></tr>" for i in cur["one_off_items"])
    unknown = "".join(f"<tr><td class=d>{_d(i['date'])}</td><td>{esc(i['merchant'])}</td><td>{esc(i['account'])}</td>"
                      f"<td class=n>{money(i['amount'], True)}</td></tr>" for i in cur["uncategorized"])

    status = ""
    if not cur["complete"]:
        status = (f'<p class="warn"><b>Partial month.</b> Statements for '
                  f'{esc(", ".join(_acct(a) for a in cur["missing_accounts"]))} don\'t cover all of '
                  f'{month_name(month)} yet, so these numbers will change.</p>')
    cov = "".join(f"<li>{esc(_acct(a))}: through {_d(iv[-1][1], year=True)}</li>"
                  for a, iv in sorted(summary["coverage"].items()))
    warn = "".join(f"<li>{esc(w)}</li>" for w in summary["warnings"])

    def section(title, body, sub=""):
        return (f'<section><h2>{title}</h2>{f"<p class=sub>{sub}</p>" if sub else ""}{body}</section>'
                if body else "")

    base_label = (f"{month_name(base_keys[0], True)} to {month_name(base_keys[-1], True)}"
                  if base_keys else "")
    return PAGE.format(
        title=f"Spending, {esc(month_name(month))}",
        month=esc(month_name(month)),
        status=status,
        tiles="".join(tiles),
        lines="".join(f"<li>{l}</li>" for l in lines),
        trend=section("Where the money went each month", trend_svg,
                      "Rent, everyday spending and one-offs, with money in shown as a line across each bar."),
        saved=section("Saved each month", saved_svg,
                      "Money in minus rent and everyday spending"
                      + (f", plus your {esc(rlabel)} contributions" if cur.get("retirement") else "")
                      + ". One-offs are left out so months compare fairly."),
        change=section(f"What changed from your average for {base_label}", change_svg,
                       "Everyday categories, biggest changes first. Red means you spent more, blue means less.")
        if change_svg else "",
        cats=section("Every category",
                     f'<div class=scroll><table><thead><tr><th>Category</th><th class=n>{esc(month_name(month, True))}</th>'
                     f'<th class=n>{esc(month_name(prev_key, True)) if prev_key else "Last month"}</th>'
                     f'<th class=n>{len(base_keys)}-month avg</th><th class=n>Change</th></tr></thead>'
                     f'<tbody>{cat_rows}</tbody></table></div>'),
        places=section("Top places", f'<div class=scroll><table><thead><tr><th>Where</th><th class=n>Visits</th>'
                       f'<th class=n>Spent</th></tr></thead><tbody>{places}</tbody></table></div>' if places else ""),
        big=section("Purchases of $150 or more", f'<div class=scroll><table><tbody>{big}</tbody></table></div>' if big else ""),
        oneoff=section("One-offs", f'<div class=scroll><table><tbody>{oneoff}</tbody></table></div>' if oneoff else "",
                       "Counted separately so they don't distort everyday spending."),
        unknown=section("Not sure what these are",
                        f'<div class=scroll><table><tbody>{unknown}</tbody></table></div>' if unknown else "",
                        "Tell me what they are and I'll add a rule so they're sorted from now on."),
        coverage=f"<ul>{cov}</ul>" + (f"<p class=warn>Check these:</p><ul>{warn}</ul>" if warn else ""),
        generated=date.today().strftime("%B %-d, %Y"),
    )


def _d(iso: str, year: bool = False) -> str:
    d = date.fromisoformat(iso)
    return d.strftime("%b %-d, %Y" if year else "%b %-d")


def _acct(a: str) -> str:
    return {"apple": "Apple Card", "chase": "Chase United Club", "checking": "BofA checking",
            "savings": "BofA savings"}.get(a, a)


# ====================================================================== SVG charts
W = 720


def _nice_max(v: float) -> float:
    for step in (500, 1000, 2000, 2500, 5000, 10000):
        if v / step <= 6:
            return step * (int(v // step) + 1), step
    return v, v / 5


def _bar_path(x, y0, w, h, r=4):
    """Column growing up from baseline y0, rounded on top only."""
    if h <= 0:
        return ""
    r = min(r, h, w / 2)
    y = y0 - h
    return (f"M{x:.1f},{y0:.1f}V{y + r:.1f}Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f}"
            f"H{x + w - r:.1f}Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f}V{y0:.1f}Z")


def _stacked_months(months, keys, focus, changes=()):
    if not keys:
        return ""
    H, top, left, bottom = 300, 16, 56, 34
    series = [("Rent", "rent", "s1"), ("Everyday", "everyday_total", "s2"), ("One-offs", "one_off_total", "s3")]
    peak = max(max(sum(max(months[k][f], 0) for _, f, _ in series), months[k]["income_total"]) for k in keys)
    ymax, step = _nice_max(peak)
    ph = H - top - bottom
    y = lambda v: top + ph - v / ymax * ph
    band = (W - left - 8) / len(keys)
    bw = min(24, band * 0.6)
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Monthly rent, everyday spending, one-offs and money in">']
    t = 0
    while t <= ymax + 1:
        out.append(f'<line class=grid x1="{left}" x2="{W - 8}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>'
                   f'<text class=tick x="{left - 8}" y="{y(t) + 4:.1f}" text-anchor="end">{_k(t)}</text>')
        t += step
    for i, k in enumerate(keys):
        m = months[k]
        cx = left + band * i + band / 2
        x = cx - bw / 2
        acc = 0.0
        tip = [month_name(k)]
        for j, (name, f, cls) in enumerate(series):
            v = max(m[f], 0)
            tip.append(f"{name}: {money(m[f])}")
            if v <= 0:
                continue
            y0 = y(acc) - (2 if acc > 0 else 0)  # 2px surface gap between segments
            h = y(acc) - y(acc + v) - (2 if acc > 0 else 0)
            last = all(max(m[ff], 0) <= 0 for _, ff, _ in series[j + 1:])
            if last:
                out.append(f'<path class="{cls}{" dim" if k != focus else ""}" d="{_bar_path(x, y0, bw, h)}"/>')
            else:
                out.append(f'<rect class="{cls}{" dim" if k != focus else ""}" x="{x:.1f}" y="{y0 - h:.1f}" '
                           f'width="{bw:.1f}" height="{max(h, 0):.1f}"/>')
            acc += v
        tip.append(f"Money in: {money(m['income_total'])}")
        iy = y(m["income_total"])
        out.append(f'<line class=inc x1="{cx - bw / 2 - 6:.1f}" x2="{cx + bw / 2 + 6:.1f}" y1="{iy:.1f}" y2="{iy:.1f}"/>')
        lab = month_name(k, True) + ("*" if not m["complete"] else "")
        out.append(f'<text class="tick{" focus" if k == focus else ""}" x="{cx:.1f}" y="{H - 12}" '
                   f'text-anchor="middle">{lab}</text>')
        out.append(f'<rect class=hit x="{left + band * i:.1f}" y="{top}" width="{band:.1f}" height="{ph}">'
                   f'<title>{esc(chr(10).join(tip))}</title></rect>')
    out.append(_change_marks(keys, changes, left, band, top, ph))
    out.append("</svg>")
    legend = ('<div class="legend"><span><i class="sw s1"></i>Rent</span><span><i class="sw s2"></i>Everyday</span>'
              '<span><i class="sw s3"></i>One-offs</span><span><i class="sw line"></i>Money in</span></div>')
    foot = '<p class="fine">* partial month</p>' if any(not months[k]["complete"] for k in keys) else ""
    return legend + '<div class="chart">' + "".join(out) + "</div>" + foot


def _change_marks(keys, changes, left, band, top, ph):
    """A thin labelled line before the first month on new pay."""
    out = []
    for c in changes:
        if c in keys and keys.index(c) > 0:
            x = left + band * keys.index(c)
            out.append(f'<line class="mark" x1="{x:.1f}" x2="{x:.1f}" y1="{top - 6}" y2="{top + ph}"/>'
                       f'<text class="marklab" x="{x + 4:.1f}" y="{top + 4}">Pay went up</text>')
    return "".join(out)


def _col(x, base, h, bw, up=True, r=4):
    """A column from y=base, h px tall, rounded at its free end."""
    if h < 0.5:
        return ""
    r = min(r, h, bw / 2)
    if up:
        return _bar_path(x, base, bw, h, r)
    yb = base + h
    return (f"M{x:.1f},{base:.1f}V{yb - r:.1f}Q{x:.1f},{yb:.1f} {x + r:.1f},{yb:.1f}"
            f"H{x + bw - r:.1f}Q{x + bw:.1f},{yb:.1f} {x + bw:.1f},{yb - r:.1f}V{base:.1f}Z")


def _saved_bars(months, keys, focus, changes=(), rlabel="Retirement"):
    if not keys:
        return ""
    H, top, left, bottom = 240, 26, 56, 34
    has_ret = any(months[k].get("retirement") for k in keys)
    tops = [max(months[k]["saved"], 0) + months[k].get("retirement", 0) for k in keys]
    lows = [min(months[k]["saved"], 0) for k in keys]
    hi, lo = max(tops + [1]), min(lows + [0])
    ymax, step = _nice_max(hi)
    ymin = -step * (int(-lo // step) + 1) if lo < 0 else 0
    ph = H - top - bottom
    y = lambda v: top + (ymax - v) / (ymax - ymin) * ph
    band = (W - left - 8) / len(keys)
    bw = min(24, band * 0.6)
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Money saved each month">']
    t = ymin
    while t <= ymax + 1:
        out.append(f'<line class="grid{" zero" if t == 0 else ""}" x1="{left}" x2="{W - 8}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>'
                   f'<text class=tick x="{left - 8}" y="{y(t) + 4:.1f}" text-anchor="end">{_k(t)}</text>')
        t += step
    for i, k in enumerate(keys):
        m = months[k]
        v, ret = m["saved"], m.get("retirement", 0)
        cx = left + band * i + band / 2
        x = cx - bw / 2
        dim = "" if k == focus else " dim"
        rate = m["savings_rate"]
        if v >= 0:
            cash_h = y(0) - y(v)
            if ret:
                out.append(f'<rect class="s1{dim}" x="{x:.1f}" y="{y(v):.1f}" width="{bw:.1f}" height="{cash_h:.1f}"/>')
                out.append(f'<path class="s3{dim}" d="{_col(x, y(v) - 2, y(v) - y(v + ret) - 2, bw)}"/>')
            else:
                out.append(f'<path class="s1{dim}" d="{_col(x, y(0), cash_h, bw)}"/>')
        else:
            out.append(f'<path class="s1{dim}" d="{_col(x, y(0), y(v) - y(0), bw, up=False)}"/>')
            if ret:
                out.append(f'<path class="s3{dim}" d="{_col(x, y(0), y(0) - y(ret), bw)}"/>')
        total = v + ret
        if k == focus:
            ly = y(max(v, 0) + ret) - 8
            out.append(f'<text class="val" x="{cx:.1f}" y="{ly:.1f}" text-anchor="middle">{money(total)}'
                       f'{f" · {rate * 100:.0f}%" if rate is not None else ""}</text>')
        out.append(f'<text class="tick{" focus" if k == focus else ""}" x="{cx:.1f}" y="{H - 12}" text-anchor="middle">'
                   f'{month_name(k, True)}{"*" if not m["complete"] else ""}</text>')
        tip = f"{month_name(k)}: saved {money(total)}"
        if ret:
            tip += f" ({money(v)} in the bank, {money(ret)} to {rlabel})"
        if rate is not None:
            tip += f", {rate * 100:.0f}% of pay"
        out.append(f'<rect class=hit x="{left + band * i:.1f}" y="{top}" width="{band:.1f}" height="{ph}">'
                   f'<title>{esc(tip)}</title></rect>')
    out.append(_change_marks(keys, changes, left, band, top, ph))
    out.append("</svg>")
    legend = (f'<div class="legend"><span><i class="sw s1"></i>Saved in the bank</span>'
              f'<span><i class="sw s3"></i>{esc(rlabel)}</span></div>') if has_ret else ""
    return legend + '<div class="chart">' + "".join(out) + "</div>"


def _diverging(rows):
    if not rows:
        return ""
    rh, top, label_w = 30, 8, 190
    H = top * 2 + rh * len(rows)
    span = max(abs(r[4]) for r in rows) or 1
    mid = label_w + (W - label_w) / 2
    half = (W - label_w) / 2 - 70
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Change in each category versus your average">',
           f'<line class="grid zero" x1="{mid:.1f}" x2="{mid:.1f}" y1="{top - 4}" y2="{H - top + 4}"/>']
    for i, (c, now, prev, avg, d) in enumerate(rows):
        cy = top + rh * i + rh / 2
        w = abs(d) / span * half
        cls = "up" if d > 0 else "down"
        bh = 16
        if w >= 1:
            r = min(4, w)
            if d > 0:
                x0, x1 = mid, mid + w
                path = (f"M{x0:.1f},{cy - bh / 2:.1f}H{x1 - r:.1f}Q{x1:.1f},{cy - bh / 2:.1f} {x1:.1f},{cy - bh / 2 + r:.1f}"
                        f"V{cy + bh / 2 - r:.1f}Q{x1:.1f},{cy + bh / 2:.1f} {x1 - r:.1f},{cy + bh / 2:.1f}H{x0:.1f}Z")
            else:
                x0, x1 = mid, mid - w
                path = (f"M{x0:.1f},{cy - bh / 2:.1f}H{x1 + r:.1f}Q{x1:.1f},{cy - bh / 2:.1f} {x1:.1f},{cy - bh / 2 + r:.1f}"
                        f"V{cy + bh / 2 - r:.1f}Q{x1:.1f},{cy + bh / 2:.1f} {x1 + r:.1f},{cy + bh / 2:.1f}H{x0:.1f}Z")
            out.append(f'<path class="{cls}" d="{path}"/>')
        tx = mid + w + 6 if d > 0 else mid - w - 6
        out.append(f'<text class=val x="{tx:.1f}" y="{cy + 4:.1f}" text-anchor="{"start" if d > 0 else "end"}">{signed(d)}</text>')
        out.append(f'<text class=cat x="0" y="{cy + 4:.1f}">{esc(c)}</text>')
        out.append(f'<rect class=hit x="0" y="{cy - rh / 2:.1f}" width="{W}" height="{rh}"><title>'
                   f'{esc(c)}: {money(now)} this month, {money(avg)} on average</title></rect>')
    out.append("</svg>")
    legend = ('<div class="legend"><span><i class="sw up"></i>Spent more</span>'
              '<span><i class="sw down"></i>Spent less</span></div>')
    return legend + '<div class="chart">' + "".join(out) + "</div>"


def _k(v: float) -> str:
    if v == 0:
        return "$0"
    return f"{'-' if v < 0 else ''}${abs(v) / 1000:g}K" if abs(v) >= 10000 else f"{'-' if v < 0 else ''}${abs(v):,.0f}"


PAGE = """<title>{title}</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,700&family=Public+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap">
<style>
/* Layout: one reading column, a ledger-style summary on top, then charts and tables in statement order. */
:root {{
  --bg: #f6f7f9; --surface: #fcfcfb; --ink: #14171c; --ink-2: #4b5260; --ink-3: #6f7685;
  --rule: #e2e5ea; --accent: #2a78d6;
  --s1: #2a78d6; --s2: #eb6834; --s3: #1baf7a; --up: #e34948; --down: #2a78d6;
  --good: #0f7a0f; --bad: #c03434; --warn-bg: #fff4dc; --warn-ink: #6b4a00;
  --display: "Bricolage Grotesque", "Segoe UI", system-ui, sans-serif;
  --body: "Public Sans", "Segoe UI", system-ui, sans-serif;
  --mono: "JetBrains Mono", ui-monospace, "SFMono-Regular", Menlo, monospace;
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg: #121417; --surface: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7; --ink-3: #9a9a92;
  --rule: #2c2f34; --accent: #3987e5;
  --s1: #3987e5; --s2: #d95926; --s3: #199e70; --up: #e66767; --down: #3987e5;
  --good: #4cc24c; --bad: #ef7b7b; --warn-bg: #3a2e12; --warn-ink: #f3d491; color-scheme: dark; }} }}
:root[data-theme="dark"] {{
  --bg: #121417; --surface: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7; --ink-3: #9a9a92;
  --rule: #2c2f34; --accent: #3987e5;
  --s1: #3987e5; --s2: #d95926; --s3: #199e70; --up: #e66767; --down: #3987e5;
  --good: #4cc24c; --bad: #ef7b7b; --warn-bg: #3a2e12; --warn-ink: #f3d491; color-scheme: dark; }}
body {{ background: var(--bg); color: var(--ink); font: 15px/1.55 var(--body); }}
main {{ max-width: 860px; margin: 0 auto; padding-block: 32px 64px;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px));
  display: grid; gap: 28px; }}
header .eyebrow {{ font: 500 12px var(--mono); letter-spacing: .08em; text-transform: uppercase; color: var(--ink-3); }}
h1 {{ font: 700 clamp(30px, 6vw, 44px)/1.05 var(--display); margin: 6px 0 0; text-wrap: balance; }}
h2 {{ font: 600 20px/1.2 var(--display); margin: 0 0 4px; text-wrap: balance; }}
.sub {{ color: var(--ink-2); margin: 0 0 12px; }}
.fine {{ color: var(--ink-3); font-size: 12px; margin: 6px 0 0; }}
.tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 1px;
  background: var(--rule); border: 1px solid var(--rule); border-radius: 10px; overflow: hidden; }}
.tile {{ background: var(--surface); padding: 16px 18px; display: grid; gap: 2px; align-content: start; }}
.tile .label {{ font-size: 13px; color: var(--ink-2); }}
.tile .value {{ font: 600 28px/1.15 var(--display); font-variant-numeric: tabular-nums; }}
.tile .sub {{ margin: 0; font-size: 13px; }}
.delta {{ font-size: 12.5px; color: var(--ink-2); }}
.delta.good span {{ color: var(--good); }} .delta.bad span {{ color: var(--bad); }} .delta.flat span {{ color: var(--ink-3); }}
ul.lines {{ margin: 0; padding-left: 20px; display: grid; gap: 6px; max-width: 68ch; }}
section {{ background: var(--surface); border: 1px solid var(--rule); border-radius: 10px; padding: 20px; min-width: 0; }}
.chart {{ overflow-x: auto; }} .chart svg {{ width: 100%; min-width: 520px; height: auto; display: block; }}
.legend {{ display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: 13px; color: var(--ink-2); margin-bottom: 8px; }}
.legend span {{ display: inline-flex; align-items: center; gap: 6px; }}
.sw {{ width: 10px; height: 10px; border-radius: 3px; display: inline-block; }}
.sw.s1 {{ background: var(--s1); }} .sw.s2 {{ background: var(--s2); }} .sw.s3 {{ background: var(--s3); }}
.sw.up {{ background: var(--up); }} .sw.down {{ background: var(--down); }}
.sw.line {{ height: 2px; width: 16px; border-radius: 1px; background: var(--ink); }}
svg .s1 {{ fill: var(--s1); }} svg .s2 {{ fill: var(--s2); }} svg .s3 {{ fill: var(--s3); }}
svg .up {{ fill: var(--up); }} svg .down {{ fill: var(--down); }}
svg .dim {{ opacity: .55; }}
svg .grid {{ stroke: var(--rule); stroke-width: 1; }} svg .grid.zero {{ stroke: var(--ink-3); }}
svg .inc {{ stroke: var(--ink); stroke-width: 2; stroke-linecap: round; }}
svg text {{ fill: var(--ink-2); font: 12px var(--body); font-variant-numeric: tabular-nums; }}
svg text.focus {{ fill: var(--ink); font-weight: 600; }}
svg text.val {{ fill: var(--ink); font-weight: 600; }}
svg text.cat {{ fill: var(--ink); font-size: 13px; }}
svg .mark {{ stroke: var(--ink-3); stroke-width: 1; }}
svg text.marklab {{ fill: var(--ink-2); font-size: 11px; }}
svg .hit {{ fill: transparent; }} svg .hit:hover {{ fill: var(--ink); fill-opacity: .04; }}
.scroll {{ overflow-x: auto; }}
table {{ width: 100%; min-width: 480px; border-collapse: collapse; font-size: 14px; }}
td.d {{ white-space: nowrap; color: var(--ink-2); }}
th {{ text-align: left; font-weight: 500; color: var(--ink-3); font-size: 12px; text-transform: uppercase; letter-spacing: .05em; }}
th, td {{ padding: 8px 10px 8px 0; border-bottom: 1px solid var(--rule); vertical-align: top; }}
tr:last-child td {{ border-bottom: 0; }}
.n {{ text-align: right; font-family: var(--mono); font-size: 13px; font-variant-numeric: tabular-nums; white-space: nowrap; }}
td.up {{ color: var(--bad); }} td.down {{ color: var(--good); }}
.tag {{ font-size: 11px; color: var(--ink-3); border: 1px solid var(--rule); border-radius: 999px; padding: 0 6px; margin-left: 4px; white-space: nowrap; }}
.note {{ font-size: 12px; color: var(--ink-3); }}
.warn {{ background: var(--warn-bg); color: var(--warn-ink); padding: 10px 14px; border-radius: 8px; margin: 0; }}
footer {{ color: var(--ink-3); font-size: 13px; }} footer ul {{ margin: 4px 0 0; padding-left: 18px; }}
</style>
<main>
<header><div class="eyebrow">Monthly spending report</div><h1>{month}</h1></header>
{status}
<div class="tiles">{tiles}</div>
<ul class="lines">{lines}</ul>
{trend}
{saved}
{change}
{cats}
{places}
{big}
{oneoff}
{unknown}
<footer><b>Statements included</b>{coverage}<p>Made {generated}. Card payments, investing and transfers between your own accounts are left out so nothing counts twice.</p></footer>
</main>
"""
