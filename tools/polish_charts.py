"""Chart construction for the polish layer. build_chart() turns a chart op: dict from
config/polish_spec.yaml into an openpyxl chart object."""
from __future__ import annotations
from openpyxl.chart import BarChart, LineChart, ScatterChart, DoughnutChart, Reference, Series
from openpyxl.chart.label import DataLabelList

_TYPES = {"bar": (BarChart, "bar"), "col": (BarChart, "col"),
          "line": (LineChart, None), "scatter": (ScatterChart, None),
          "doughnut": (DoughnutChart, None)}


def _ref(wb, spec):
    """Parse 'Sheet Name'!A1:B9 (quoted or bare) into an openpyxl Reference."""
    sheet, _, rng = spec.rpartition("!")
    sheet = sheet.strip("'")
    return Reference(wb[sheet], range_string=f"'{sheet}'!{rng}")


def build_chart(wb, o, colour):
    cls, subtype = _TYPES[o["type"]]
    ch = cls()
    if subtype:
        ch.type = subtype
    ch.title = o.get("title")
    ch.height, ch.width = o["size"]["h"], o["size"]["w"]

    legend = o.get("legend", True)
    if legend is False:
        ch.legend = None
    elif isinstance(legend, str):
        ch.legend.position = {"bottom": "b", "right": "r", "top": "t"}[legend]

    if o["type"] == "scatter":
        # X must be the LEFT column - see spec step 8
        xs, ys = _ref(wb, o["x"]["ref"]), _ref(wb, o["y"]["ref"])
        ser = Series(ys, xs, title_from_data=True)
        ser.marker.symbol = "none"
        ch.series.append(ser)
    else:
        ch.add_data(_ref(wb, o["data"]["ref"]),
                    titles_from_data=o["data"].get("titles_from_data", True))
        if o.get("cats"):
            ch.set_categories(_ref(wb, o["cats"]["ref"]))

    for axis_key, axis in (("x", getattr(ch, "x_axis", None)),
                           ("y", getattr(ch, "y_axis", None))):
        cfg = o.get(axis_key)
        if not cfg or axis is None:
            continue
        if cfg.get("title"):
            axis.title = cfg["title"]
        if cfg.get("numfmt"):
            axis.numFmt = cfg["numfmt"]

    if o.get("reverse_categories"):
        # horizontal bar: maxMin puts the largest category at the TOP
        ch.y_axis.scaling.orientation = "maxMin"

    for ser, style in zip(ch.series, o.get("series_style", [])):
        if style.get("fill"):
            ser.graphicalProperties.solidFill = colour(style["fill"])
        if style.get("line"):
            ser.graphicalProperties.line.solidFill = colour(style["line"])
        if style.get("width"):
            ser.graphicalProperties.line.width = style["width"]
        if o["type"] == "line":
            ser.smooth = False

    dl = o.get("data_labels")
    if dl:
        ch.dataLabels = DataLabelList()
        ch.dataLabels.showVal = dl.get("value", False)
        ch.dataLabels.showPercent = dl.get("percent", False)
        ch.dataLabels.showCatName = dl.get("category", False)
    return ch
