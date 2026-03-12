from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape
import zipfile

import pandas as pd
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
TASK5_DIR = ROOT / "Task5"
OUTPUT_DOCX = TASK5_DIR / "task5_subreport.docx"


@dataclass
class ImageSpec:
    path: Path
    rid: str
    name: str
    rel_path: str
    content_type: str
    cx: int
    cy: int


def eur_m(value: float) -> str:
    return f"EUR {value / 1_000_000:.1f}M"


def fmt_int(value: float) -> str:
    return f"{int(round(value)):,}"


def fmt_pct(value: float, decimals: int = 1) -> str:
    return f"{value:.{decimals}f}%"


def fmt_num(value: float, decimals: int = 2) -> str:
    return f"{value:.{decimals}f}"


def build_narrative() -> list[dict[str, str]]:
    kpi = pd.read_csv(TASK5_DIR / "output" / "network_kpis_by_year.csv")
    container = pd.read_csv(TASK5_DIR / "output" / "subtask_5_2_container_space.csv")
    profit = pd.read_csv(TASK5_DIR / "output" / "subtask_5_12_profitability.csv")
    comparison = pd.read_csv(ROOT / "comparison" / "data" / "task4_vs_task5_yearly_comparison.csv")
    tradeoff = pd.read_csv(ROOT / "comparison" / "data" / "pi_tradeoff_metrics.csv")

    row_2030 = kpi.loc[kpi["year"] == 2030].iloc[0]
    container_2030 = container.loc[container["year"] == 2030].iloc[0]
    profit_2030 = profit.loc[profit["year"] == 2030].iloc[0]
    comp_2030 = comparison.loc[comparison["year"] == 2030].iloc[0]
    tradeoff_2030 = tradeoff.loc[tradeoff["year"] == 2030].set_index("metric_key")

    pi_units_total = comparison["pi_realized_units"].sum()
    old_units_total = comparison["old_realized_units"].sum()
    pi_transport_per_unit = comparison["pi_transport_cost_eur"].sum() / pi_units_total
    old_transport_per_unit = comparison["old_transport_cost_eur"].sum() / old_units_total
    pi_scope_per_unit = comparison["pi_network_scope_cost_eur"].sum() / pi_units_total
    old_scope_per_unit = comparison["old_network_scope_cost_eur"].sum() / old_units_total

    horizon_units_adv = (pi_units_total / old_units_total - 1.0) * 100.0
    horizon_scope_reduction = (1.0 - pi_scope_per_unit / old_scope_per_unit) * 100.0
    horizon_transport_reduction = (1.0 - pi_transport_per_unit / old_transport_per_unit) * 100.0

    paragraphs = [
        {
            "style": "Title",
            "text": "Task 5 Subreport: PI Hyperconnected Transportation",
        },
        {
            "style": "Normal",
            "text": (
                "This subreport addresses the Task 5 case questions on network design, "
                "simulation-backed performance, and PI-versus-non-PI comparison. The writeup "
                "uses the case PDF, the Task 5 notebook and source pipeline, and the final CSV "
                "and figure outputs stored under Task5/output and comparison/."
            ),
        },
        {
            "style": "Heading1",
            "text": "Network Design",
        },
        {
            "style": "Normal",
            "text": (
                "The implemented design is a phased multi-tier network. Rotterdam is the fixed "
                "port entry; Euro DCs open from 2027 to 2030; peri-urban hubs are created from "
                "the metro-city layer; and non-metro demand centroids are kept as sinks for "
                "coverage checks. Relay hubs are set algorithmically whenever a DC-to-market trip "
                "exceeds the 11-hour single-driver threshold. Candidate relays are placed at the "
                "mid-journey point, clustered within 80 km to avoid hub proliferation, and merged "
                "with nearby peri-urban hubs when possible so the network reuses existing nodes "
                "instead of adding unnecessary infrastructure."
            ),
        },
        {
            "style": "Normal",
            "text": (
                "Lane generation follows the same logic as the case brief: port-to-DC trunk legs, "
                "DC-to-DC transfer links, direct DC-to-hub lanes for markets within four driving "
                "hours, DC-to-relay lanes for long-haul coverage, relay-to-hub feeder legs, and "
                "short hub corridors. Routes are then chosen by shortest elapsed time, not just "
                "distance, using one hour of dwell at relay-only stops and two hours at "
                "consolidation-capable hubs. This gives a defensible layered design that "
                "prioritizes daily flow, relay feasibility, and low detour. By 2030 the network "
                "stabilizes at 4 DCs, 269 peri-urban hubs, 167 relay hubs, and 8,151 active lanes, "
                "with mean detour held to "
                f"{fmt_num(float(row_2030['mean_detour']), 3)}."
            ),
        },
        {
            "style": "Caption",
            "text": "Figure 1. 2030 Task 5 network map from the final roadmap output.",
        },
        {"style": "Image", "text": "fig_5_1_network_map_2030.png"},
        {
            "style": "Heading1",
            "text": "Simulation Results",
        },
        {
            "style": "Normal",
            "text": (
                "The yearly pipeline activates nodes, builds routes, simulates demand and service, "
                "sizes DC capacity, and then evaluates cost, carbon, autonomy, and profitability. "
                f"In 2030 the PI design reaches {fmt_pct(float(row_2030['coverage_pct']), 1)} "
                "feasible-pair coverage with "
                f"{fmt_pct(float(row_2030['relay_readiness_pct']), 2)} relay readiness. Mean "
                f"service OTD is {fmt_num(float(row_2030['mean_service_otd_hr']))} hours and the "
                f"p95 is {fmt_num(float(row_2030['p95_service_otd_hr']))} hours, which shows the "
                "network is fast on average but still carries a long multi-hop tail. Container and "
                "packaging logic materially improve transport density: the PI design cuts pallet "
                "need by "
                f"{fmt_pct(float(container_2030['pallet_saving_pct']))}, TEU need by "
                f"{fmt_pct(float(container_2030['teu_saving_pct']))}, and unit cube by "
                f"{fmt_pct(float(container_2030['vol_saving_pct']))}. In 2030 that reduces ocean "
                f"loads from {fmt_int(float(container_2030['teus_nonpi']))} TEUs to "
                f"{fmt_int(float(container_2030['teus_pi']))} TEUs while supporting a PI margin of "
                f"{eur_m(float(profit_2030['pi_margin_eur']))} "
                f"({fmt_pct(float(profit_2030['pi_margin_pct']), 2)})."
            ),
        },
        {
            "style": "Caption",
            "text": "Figure 2. Monte Carlo OTD output used for Task 5 service assessment.",
        },
        {"style": "Image", "text": "fig_5_3_otd_simulation.png"},
        {
            "style": "Caption",
            "text": "Figure 3. Simulation-backed DC capacity sizing across the rollout horizon.",
        },
        {"style": "Image", "text": "fig_5_10_dc_capacity.png"},
        {
            "style": "Heading1",
            "text": "Comparison Against the Old Network",
        },
        {
            "style": "Normal",
            "text": (
                "The strongest evidence for the PI design is the matched comparison against the "
                "Task 4 old network. In 2030 realized demand rises from "
                f"{fmt_int(float(comp_2030['old_realized_units']))} units to "
                f"{fmt_int(float(comp_2030['pi_realized_units']))} units, a "
                f"{fmt_pct(float(comp_2030['units_uplift_pct']))} uplift. Transport cost per unit "
                f"falls from EUR {fmt_num(float(comp_2030['old_transport_cost_per_unit_eur']))} to "
                f"EUR {fmt_num(float(comp_2030['pi_transport_cost_per_unit_eur']))}, and matched "
                "network-scope cost per unit falls from "
                f"EUR {fmt_num(float(comp_2030['old_network_scope_cost_per_unit_eur']))} to "
                f"EUR {fmt_num(float(comp_2030['pi_network_scope_cost_per_unit_eur']))}, a "
                f"{fmt_pct(abs(float(comp_2030['network_scope_cost_per_unit_change_pct'])))} "
                "reduction. Across the full 2027-2034 horizon, PI delivers "
                f"{fmt_pct(horizon_units_adv)} more realized units, "
                f"{fmt_pct(horizon_transport_reduction)} lower transport cost per unit, and "
                f"{fmt_pct(horizon_scope_reduction)} lower network-scope cost per unit."
            ),
        },
        {
            "style": "Normal",
            "text": (
                "The tradeoff is orchestration complexity rather than economics. In 2030 the "
                "remaining gaps are a "
                f"{fmt_num(float(tradeoff_2030.loc['coverage_shortfall_pct_pts', 'pi_value']))} "
                "percentage-point coverage shortfall to full coverage, "
                f"{fmt_pct(float(tradeoff_2030.loc['relay_unready_share_pct', 'pi_value']))} of "
                "the relay mesh not fully ready, and a "
                f"{fmt_num(float(tradeoff_2030.loc['service_tail_spread_hr', 'pi_value']))}-hour "
                "gap between mean and p95 service time. These are consistent with a network that "
                "wins on reach and unit economics by adding many more operating touchpoints and "
                "more multi-hop coordination."
            ),
        },
        {
            "style": "Caption",
            "text": "Figure 4. Task 5 versus Task 4 matched KPI comparison.",
        },
        {"style": "Image", "text": "pi_vs_old_performance_overview.png"},
    ]

    word_count = sum(
        len(block["text"].split())
        for block in paragraphs
        if block["style"] not in {"Image", "Title", "Heading1", "Caption"}
    )
    if word_count > 800:
        raise ValueError(f"Report body exceeds 800 words: {word_count}")
    return paragraphs


def image_specs() -> dict[str, ImageSpec]:
    image_paths = [
        TASK5_DIR / "output" / "fig_5_1_network_map_2030.png",
        TASK5_DIR / "output" / "fig_5_3_otd_simulation.png",
        TASK5_DIR / "output" / "fig_5_10_dc_capacity.png",
        ROOT / "comparison" / "figures" / "pi_vs_old_performance_overview.png",
    ]
    specs: dict[str, ImageSpec] = {}
    max_width_emu = int(6.3 * 914400)

    for idx, path in enumerate(image_paths, start=1):
        if not path.exists():
            raise FileNotFoundError(path)
        with Image.open(path) as img:
            width_px, height_px = img.size
        width_emu = width_px * 9525
        height_emu = height_px * 9525
        scale = min(1.0, max_width_emu / width_emu)
        ext = path.suffix.lower().lstrip(".")
        if ext == "jpg":
            ext = "jpeg"
        if ext not in {"png", "jpeg"}:
            raise ValueError(f"Unsupported image format for {path}: {ext}")
        content_type = "image/png" if ext == "png" else "image/jpeg"
        specs[path.name] = ImageSpec(
            path=path,
            rid=f"rId{idx + 1}",
            name=path.name,
            rel_path=f"media/image{idx}.{ext}",
            content_type=content_type,
            cx=int(width_emu * scale),
            cy=int(height_emu * scale),
        )
    return specs


def para_xml(text: str, style: str) -> str:
    safe = escape(text)
    return (
        "<w:p>"
        f"<w:pPr><w:pStyle w:val=\"{style}\"/></w:pPr>"
        f"<w:r><w:t xml:space=\"preserve\">{safe}</w:t></w:r>"
        "</w:p>"
    )


def image_xml(spec: ImageSpec, docpr_id: int) -> str:
    return f"""
<w:p>
  <w:pPr><w:pStyle w:val="ImageBlock"/></w:pPr>
  <w:r>
    <w:drawing>
      <wp:inline distT="0" distB="0" distL="0" distR="0">
        <wp:extent cx="{spec.cx}" cy="{spec.cy}"/>
        <wp:docPr id="{docpr_id}" name="{escape(spec.name)}"/>
        <wp:cNvGraphicFramePr>
          <a:graphicFrameLocks noChangeAspect="1"/>
        </wp:cNvGraphicFramePr>
        <a:graphic>
          <a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
            <pic:pic>
              <pic:nvPicPr>
                <pic:cNvPr id="0" name="{escape(spec.name)}"/>
                <pic:cNvPicPr/>
              </pic:nvPicPr>
              <pic:blipFill>
                <a:blip r:embed="{spec.rid}"/>
                <a:stretch><a:fillRect/></a:stretch>
              </pic:blipFill>
              <pic:spPr>
                <a:xfrm>
                  <a:off x="0" y="0"/>
                  <a:ext cx="{spec.cx}" cy="{spec.cy}"/>
                </a:xfrm>
                <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
              </pic:spPr>
            </pic:pic>
          </a:graphicData>
        </a:graphic>
      </wp:inline>
    </w:drawing>
  </w:r>
</w:p>
""".strip()


def build_document_xml(blocks: list[dict[str, str]], specs: dict[str, ImageSpec]) -> str:
    body_parts: list[str] = []
    docpr_id = 1
    for block in blocks:
        if block["style"] == "Image":
            body_parts.append(image_xml(specs[block["text"]], docpr_id))
            docpr_id += 1
        else:
            body_parts.append(para_xml(block["text"], block["style"]))

    sect_pr = """
<w:sectPr>
  <w:pgSz w:w="12240" w:h="15840"/>
  <w:pgMar w:top="1080" w:right="1080" w:bottom="1080" w:left="1080" w:header="720" w:footer="720" w:gutter="0"/>
</w:sectPr>
""".strip()

    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:wpc="http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas"
 xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"
 xmlns:o="urn:schemas-microsoft-com:office:office"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
 xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"
 xmlns:v="urn:schemas-microsoft-com:vml"
 xmlns:wp14="http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing"
 xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
 xmlns:w10="urn:schemas-microsoft-com:office:word"
 xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
 xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml"
 xmlns:wpg="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup"
 xmlns:wpi="http://schemas.microsoft.com/office/word/2010/wordprocessingInk"
 xmlns:wne="http://schemas.microsoft.com/office/word/2006/wordml"
 xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"
 xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
 xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"
 mc:Ignorable="w14 wp14">
  <w:body>
    {''.join(body_parts)}
    {sect_pr}
  </w:body>
</w:document>
"""


def styles_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:docDefaults>
    <w:rPrDefault>
      <w:rPr>
        <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/>
        <w:sz w:val="22"/>
      </w:rPr>
    </w:rPrDefault>
  </w:docDefaults>
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal">
    <w:name w:val="Normal"/>
    <w:qFormat/>
    <w:pPr><w:spacing w:after="140" w:line="300" w:lineRule="auto"/></w:pPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Title">
    <w:name w:val="Title"/>
    <w:basedOn w:val="Normal"/>
    <w:pPr><w:spacing w:after="220"/><w:jc w:val="center"/></w:pPr>
    <w:rPr><w:b/><w:sz w:val="30"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading1">
    <w:name w:val="heading 1"/>
    <w:basedOn w:val="Normal"/>
    <w:pPr><w:spacing w:before="180" w:after="100"/></w:pPr>
    <w:rPr><w:b/><w:sz w:val="26"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Caption">
    <w:name w:val="Caption"/>
    <w:basedOn w:val="Normal"/>
    <w:pPr><w:spacing w:before="40" w:after="60"/></w:pPr>
    <w:rPr><w:i/><w:sz w:val="18"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="ImageBlock">
    <w:name w:val="ImageBlock"/>
    <w:basedOn w:val="Normal"/>
    <w:pPr><w:jc w:val="center"/><w:spacing w:after="160"/></w:pPr>
  </w:style>
</w:styles>
"""


def content_types_xml(specs: dict[str, ImageSpec]) -> str:
    image_overrides = []
    default_exts = {"rels": "application/vnd.openxmlformats-package.relationships+xml", "xml": "application/xml"}
    for spec in specs.values():
        ext = spec.rel_path.rsplit(".", 1)[1]
        if ext not in default_exts:
            default_exts[ext] = spec.content_type

    defaults = "".join(
        f'<Default Extension="{ext}" ContentType="{ctype}"/>'
        for ext, ctype in sorted(default_exts.items())
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  {defaults}
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>
"""


def root_rels_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>
"""


def document_rels_xml(specs: dict[str, ImageSpec]) -> str:
    image_rels = "".join(
        f'<Relationship Id="{spec.rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="{spec.rel_path}"/>'
        for spec in specs.values()
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
  {image_rels}
</Relationships>
"""


def core_xml() -> str:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
 xmlns:dc="http://purl.org/dc/elements/1.1/"
 xmlns:dcterms="http://purl.org/dc/terms/"
 xmlns:dcmitype="http://purl.org/dc/dcmitype/"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>Task 5 Subreport</dc:title>
  <dc:creator>Codex</dc:creator>
  <cp:lastModifiedBy>Codex</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified>
</cp:coreProperties>
"""


def app_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
 xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Microsoft Office Word</Application>
</Properties>
"""


def write_docx(output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    blocks = build_narrative()
    specs = image_specs()
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml(specs))
        zf.writestr("_rels/.rels", root_rels_xml())
        zf.writestr("docProps/core.xml", core_xml())
        zf.writestr("docProps/app.xml", app_xml())
        zf.writestr("word/document.xml", build_document_xml(blocks, specs))
        zf.writestr("word/styles.xml", styles_xml())
        zf.writestr("word/_rels/document.xml.rels", document_rels_xml(specs))
        for spec in specs.values():
            zf.write(spec.path, f"word/{spec.rel_path}")


if __name__ == "__main__":
    write_docx(OUTPUT_DOCX)
    print(f"Wrote {OUTPUT_DOCX}")
