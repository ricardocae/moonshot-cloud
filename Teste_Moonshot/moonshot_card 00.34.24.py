import os
# moonshot_card.py — cards com ÍCONES (TP/STOP)
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
import platform

# ====== CONTROLES DE LAYOUT (mesmos do TP) ======
PILL_Y_OFFSET     = +26
LABELS_Y_OFFSET   = +14
STOP_Y_OFFSET     = +16
STOP_VALUE_SCALE  = 0.65
SYMBOL_Y_OFFSET   = -14
# =================================
# ====== ROI helper ======
def _parse_lev(lev: str) -> float:
    try:
        s = ''.join([c for c in str(lev) if (c.isdigit() or c=='.')])
        v = float(s) if s else 1.0
        return v if v > 0 else 1.0
    except Exception:
        return 1.0

def _calc_roi(entry: float, last: float, lev: float, side: str) -> float:
    dir_ = 1.0 if str(side).upper() == "LONG" else -1.0
    return dir_ * ((float(last) - float(entry)) / max(float(entry), 1e-12)) * float(lev) * 100.0
# ========================
==============

BASE = Path(__file__).resolve().parent
F_BOLD = BASE / "Myriad Pro Bold.ttf"
F_REG  = BASE / "Myriad Pro Regular.ttf"

WHITE=(230,235,240,255)
DIM=(170,180,190,255)
GREEN=(42,214,95,255)
RED=(234,69,53,255)
PILL_LONG=(29,132,86,255); PILL_SHORT=(200,40,40,255)

def _tt(pref_path, size, **kw):
    sys = platform.system()
    candidates = [pref_path]
    if sys == "Darwin":
        candidates += [
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/Library/Fonts/Arial Bold.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
        ]
    elif sys == "Linux":
        candidates += [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    else:
        candidates += [
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/segoeui.ttf",
        ]
    for c in candidates:
        try:
            return ImageFont.truetype(str(c), size=size, **kw)
        except Exception:
            continue
    return ImageFont.load_default()

def _load_icon(name: str, size: int):
    for cand in [BASE / "assets/icons" / name, BASE / "icons" / name]:
        if cand.exists():
            im = Image.open(cand).convert("RGBA")
            if size:
                im = im.resize((size, size), Image.LANCZOS)
            return im
    return None

def _common_fonts(k: float):
    f_title = _tt(F_BOLD, int(46*k))
    f_pill  = _tt(F_REG,  int(25*k))
    f_small = _tt(F_REG,  int(18*k))
    f_big   = _tt(F_BOLD, int(86*k))
    f_num   = _tt(F_BOLD, int(38*k))
    f_stopv = _tt(F_BOLD, int(38*k*STOP_VALUE_SCALE))
    f_tp    = _tt(F_BOLD, int(30*k))
    return f_title, f_pill, f_small, f_big, f_num, f_stopv, f_tp

def _grid(W: int):
    k = W/936.0
    left   = int(63*k)
    y_sym  = int(150*k) + int(SYMBOL_Y_OFFSET*k)
    y_hdr  = int(205*k)
    y_roi  = int(245*k)
    y_lab  = int(335*k) + int(LABELS_Y_OFFSET*k)
    y_val  = int(375*k)
    y_stop = int(430*k) + int(STOP_Y_OFFSET*k)
    return k, left, y_sym, y_hdr, y_roi, y_lab, y_val, y_stop

def _draw_pill(draw, k, left, y_sym, symbol, side, leverage, f_title, f_pill, force_color=None):
    pill_txt = f"{side.capitalize()} {leverage}"
    pill_w = draw.textlength(pill_txt, font=f_pill) + int(55*k)
    pill_h = int(38*k)
    x_sym_right = left + int(draw.textlength(symbol, font=f_title))
    base_y_pill = y_sym - int(28*k)
    y_pill = base_y_pill + int(PILL_Y_OFFSET*k)
    x_pill = x_sym_right + int(20*k)
    draw.rounded_rectangle((x_pill, y_pill, x_pill+pill_w, y_pill+pill_h), radius=int(pill_h/2),
                           fill=(force_color if force_color is not None else (PILL_LONG if side.upper()=="LONG" else PILL_SHORT)))
    tx = x_pill + (pill_w - draw.textlength(pill_txt, font=f_pill))//2
    ty = y_pill + (pill_h - f_pill.size)//2
    draw.text((tx,ty), pill_txt, font=f_pill, fill=(220,245,235,255))

def generate_trade_card(
    symbol: str,
    side: str,
    leverage: str,
    tp_label: str,       # "TP1"/"TP2"/"TP3"
    roi_pct: float,
    entry_price: float,
    last_price: float,
    stop_text: str,
    out_path: str,
    bg_path: str,
):
    im = Image.open(bg_path).convert("RGBA")
    W,H = im.size
    draw = ImageDraw.Draw(im)

    k, left, y_sym, y_hdr, y_roi, y_lab, y_val, y_stop = _grid(W)
    f_title, f_pill, f_small, f_big, f_num, f_stopv, f_tp = _common_fonts(k)

    # SYMBOL
    draw.text((left, y_sym), symbol, font=f_title, fill=WHITE, stroke_width=1, stroke_fill=(0,0,0,180))

    # pill
    _draw_pill(draw, k, left, y_sym, symbol, side, leverage, f_title, f_pill, force_color=None)

    # ROI header + ícone
    icon_t = _load_icon("target.png", int(32*k))
    x = left
    draw.text((x, y_hdr), "ROI ", font=f_pill, fill=DIM)
    x += int(draw.textlength("ROI ", font=f_pill))
    if icon_t:
        im.paste(icon_t, (x, y_hdr + (f_pill.size - icon_t.size[1])//2 - int(4*k)), icon_t)
        x += icon_t.size[0] + int(8*k)
    draw.text((x, y_hdr), f"{tp_label}", font=f_tp, fill=WHITE)

    # ROI big
    draw.text((left, y_roi), f"{roi_pct:+.2f}%", font=f_big,
              fill=GREEN if roi_pct>=0 else RED, stroke_width=0, stroke_fill=(0,0,0,140))

    # labels
    col2 = left + int(248*k)
    draw.text((left, y_lab), "Entry Price", font=f_small, fill=DIM)
    draw.text((col2,  y_lab), "Last Traded Price", font=f_small, fill=DIM)

    # values
    draw.text((left, y_val), f"{entry_price:.3f}", font=f_num, fill=WHITE, stroke_width=1, stroke_fill=(0,0,0,150))
    draw.text((col2, y_val), f"{last_price:.3f}",  font=f_num, fill=WHITE, stroke_width=1, stroke_fill=(0,0,0,150))

    # STOP line (ícone + prefixo + valor em bold menor)
    icon_a = _load_icon("arrow.png", int(38*k))
    x = left
    if icon_a:
        im.paste(icon_a, (x, y_stop + (f_pill.size - icon_a.size[1])//2 - int(1*k)), icon_a)
        x += icon_a.size[0] + int(6*k)
    prefix = "Stop movido para: "
    draw.text((x, y_stop), prefix, font=f_pill, fill=WHITE)
    off = x + int(draw.textlength(prefix, font=f_pill))
    draw.text((off, y_stop), str(stop_text), font=f_stopv, fill=WHITE)

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    im.save(out_path)
    return out_path

def generate_stop_card(
    symbol: str,
    side: str,
    leverage: str,
    roi_pct: float,      # negativo!
    entry_price: float,
    filled_price: float, # preço do fill (SL)
    sl_price: float | None,
    out_path: str,
    bg_path: str,
):
    im = Image.open(bg_path).convert("RGBA")
    W,H = im.size
    draw = ImageDraw.Draw(im)

    k, left, y_sym, y_hdr, y_roi, y_lab, y_val, y_stop = _grid(W)
    f_title, f_pill, f_small, f_big, f_num, f_stopv, f_tp = _common_fonts(k)

    # SYMBOL
    draw.text((left, y_sym), symbol, font=f_title, fill=WHITE, stroke_width=1, stroke_fill=(0,0,0,180))

    # pill
    _draw_pill(draw, k, left, y_sym, symbol, side, leverage, f_title, f_pill, force_color=PILL_SHORT)

    # Header "STOP LOSS" com ícone
    icon_s = _load_icon("stop.png", int(30*k))
    x = left
    if icon_s:
        im.paste(icon_s, (x, y_hdr + (f_pill.size - icon_s.size[1])//2 - int(2*k)), icon_s)
        x += icon_s.size[0] + int(8*k)
    draw.text((x, y_hdr), "STOP LOSS", font=f_tp, fill=WHITE)

    # ROI big (vermelho; calculado automaticamente quando possível)
    try:
        lev_num = _parse_lev(leverage)
        roi_val = _calc_roi(entry_price, filled_price, lev_num, side)
    except Exception:
        roi_val = float(roi_pct)
    draw.text((left, y_roi), f"{roi_val:+.2f}%", font=f_big,
              fill=RED, stroke_width=0, stroke_fill=(0,0,0,140))

    # labels
    col2 = left + int(248*k)
    draw.text((left, y_lab), "Entry Price", font=f_small, fill=DIM)
    draw.text((col2,  y_lab), "Filled Price", font=f_small, fill=DIM)

    # values
    draw.text((left, y_val), f"{entry_price:.3f}", font=f_num, fill=WHITE, stroke_width=1, stroke_fill=(0,0,0,150))
    draw.text((col2, y_val), f"{filled_price:.3f}",  font=f_num, fill=WHITE, stroke_width=1, stroke_fill=(0,0,0,150))

    # linha extra: SL (se houver)
    if sl_price is not None:
        icon_a = _load_icon("arrow.png", int(38*k))
        x = left
        if icon_a:
            im.paste(icon_a, (x, y_stop + (f_pill.size - icon_a.size[1])//2 - int(1*k)), icon_a)
            x += icon_a.size[0] + int(6*k)
        prefix = "Stop (SL): "
        draw.text((x, y_stop), prefix, font=f_pill, fill=WHITE)
        off = x + int(draw.textlength(prefix, font=f_pill))
        draw.text((off, y_stop), f"{sl_price}", font=f_stopv, fill=WHITE)

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    im.save(out_path)
    return out_path