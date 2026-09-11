<?php
// Offline render of the GOLD panel — the page as Luzia would see it today.
// Same code path as production: entitlement.php + gold-panel.php, no stubs
// beyond esc_html/esc_attr, which the panel already guards.
require __DIR__ . '/entitlement.php';
require __DIR__ . '/gold-panel.php';

$d = json_decode( file_get_contents( __DIR__ . '/luzia_data.json' ), true );

// 🔴 No billing anchor on the signed contract, so no cycle. The panel is built
// to say so rather than invent one — this render shows that real state.
$hours  = null;
$assets = array();   // nothing delivered under GOLD yet

$html = mwm_rm_gold_panel( $d, $hours, $assets );
$css = <<<'CSS'
:root{--bg:#fbfaf8;--card:#fff;--ink:#1b1a18;--mut:#6b6862;--line:#e6e2da;
--gold:#a8813c;--accent:#8a6a2f;--warn:#8a3b2f;--ok:#3d6b4a;--radius:14px}
@media(prefers-color-scheme:dark){:root{--bg:#151412;--card:#1e1d1a;--ink:#efece6;
--mut:#a09b92;--line:#332f2a;--gold:#d4a857;--accent:#e0b96e;--warn:#e0836f;--ok:#7fb992}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:16px/1.6 ui-sans-serif,-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.rm-portal{max-width:760px;margin:0 auto;padding:32px 20px 72px}
.rm-header{padding:8px 0 28px;border-bottom:1px solid var(--line);margin-bottom:26px}
.rm-client{margin:0;color:var(--mut);font-size:.82rem;letter-spacing:.14em;text-transform:uppercase}
.rm-header h1{margin:.28em 0 .12em;font-size:1.95rem;letter-spacing:-.02em;color:var(--gold);font-weight:650}
.rm-plan-line{margin:0;color:var(--mut);font-size:.95rem}
.rm-card{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
padding:22px 22px 20px;margin:0 0 18px}
.rm-card h2{margin:0 0 14px;font-size:1.02rem;letter-spacing:-.01em;font-weight:650}
.rm-card h3{margin:0 0 4px;font-size:.98rem;font-weight:620}
.rm-card ul{margin:0;padding-left:1.15em}.rm-card li{margin:.34em 0}
.rm-lede{margin:0 0 14px;color:var(--mut);font-size:.93rem}
.rm-meter{margin:0 0 18px}
.rm-meter-head{display:flex;justify-content:space-between;align-items:baseline;gap:12px}
.rm-meter-label{font-weight:600;font-size:.95rem}
.rm-meter-figure{color:var(--accent);font-weight:650;font-variant-numeric:tabular-nums}
.rm-bar{height:7px;background:var(--line);border-radius:99px;overflow:hidden;margin:9px 0 7px}
.rm-bar span{display:block;height:100%;background:var(--gold);border-radius:99px}
.rm-meter-sub{margin:0;font-size:.87rem;color:var(--mut)}
.rm-meter-note{margin:.7em 0 0;font-size:.85rem;color:var(--mut)}
.rm-cycle-window{margin:0 0 16px;color:var(--mut);font-size:.9rem}
.rm-expiry{margin:14px 0 0;font-size:.88rem;color:var(--warn);font-weight:520}
.rm-pending,.rm-empty{margin:0;color:var(--mut);font-size:.94rem}
.rm-delivered-count{margin:0 0 12px;font-weight:600}
.rm-asset-list{list-style:none;padding:0;margin:0}
.rm-asset{display:flex;flex-wrap:wrap;gap:10px;align-items:baseline;
padding:9px 0;border-top:1px solid var(--line)}
.rm-asset-title{font-weight:560}
.rm-asset-kind{font-size:.74rem;text-transform:uppercase;letter-spacing:.08em;
color:var(--mut);border:1px solid var(--line);border-radius:99px;padding:1px 8px}
.rm-asset-date{color:var(--mut);font-size:.85rem;margin-left:auto}
.rm-request{padding:14px 0;border-top:1px solid var(--line)}
.rm-request:first-of-type{border-top:0;padding-top:0}
.rm-request-state{margin:0 0 6px;font-size:.8rem;text-transform:uppercase;
letter-spacing:.09em;color:var(--accent);font-weight:640}
.rm-request-date,.rm-request-total{margin:.18em 0;font-size:.93rem}
.rm-request-total{font-weight:640;font-variant-numeric:tabular-nums}
.rm-request-breakdown{font-weight:400;color:var(--mut);font-size:.86rem}
.rm-request-caveat{margin:.6em 0 0;font-size:.88rem;color:var(--warn)}
.rm-rate-table{width:100%;border-collapse:collapse;font-size:.93rem}
.rm-rate-table th{text-align:left;font-weight:540;padding:9px 0;
border-top:1px solid var(--line);vertical-align:top}
.rm-rate-table td{padding:9px 0;border-top:1px solid var(--line);
text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
.rm-rate-table tr:first-child th,.rm-rate-table tr:first-child td{border-top:0}
.rm-price{font-weight:640;color:var(--accent)}
.rm-rate-note td{text-align:left;border-top:0;padding:0 0 8px;
color:var(--mut);font-size:.85rem;white-space:normal}
.rm-terms-list{margin:0;display:grid;grid-template-columns:180px 1fr;gap:10px 18px;font-size:.93rem}
.rm-terms-list dt{font-weight:600}.rm-terms-list dd{margin:0;color:var(--mut)}
@media(max-width:560px){.rm-terms-list{grid-template-columns:1fr;gap:2px 0}
.rm-terms-list dd{margin:0 0 10px}.rm-asset-date{margin-left:0}
.rm-portal{padding:22px 16px 56px}}
CSS;

echo "<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">";
echo "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">";
echo "<title>Luzia Costa — MWM ROADMAP</title><style>{$css}</style></head><body>\n";
echo $html;
echo "\n</body></html>\n";
