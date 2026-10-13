"""
MSPDI XML schedule builder for illustrative SRA test cases.

Emits Microsoft Project 2007 XML Data Interchange (MSPDI) files that can be
read by MPXJ (and therefore by ProjectLibre, MS Project, and RefProject's
Python engine via the MPXJ pipeline).

Each schedule below illustrates one key concept in stochastic schedule
analysis. Durations are in DAYS (8-hour working days, Mon-Fri).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable
import xml.etree.ElementTree as ET
import xml.dom.minidom as minidom


# MSPDI uses ISO 8601 duration: PT{H}H{M}M{S}S for hours/minutes/seconds.
# Working day = 8 hours. We express duration in hours so MS Project / MPXJ
# render the schedule on a standard 5-day, 8-hour calendar.
HOURS_PER_DAY = 8
MINUTES_PER_DAY = HOURS_PER_DAY * 60
WORK_START = "08:00:00"
WORK_FINISH = "16:00:00"


@dataclass
class Task:
    uid: int                  # unique ID, also used in PredecessorUID
    name: str
    duration_days: float      # 0 = milestone
    predecessors: list[int] = field(default_factory=list)  # list of predecessor UIDs (FS, 0 lag)
    is_summary: bool = False
    outline_level: int = 1
    notes: str = ""

    @property
    def is_milestone(self) -> bool:
        return self.duration_days == 0 and not self.is_summary


@dataclass
class Schedule:
    name: str
    start_date: datetime
    tasks: list[Task]
    description: str = ""


def _iso_dur(days: float) -> str:
    hours = int(round(days * HOURS_PER_DAY))
    return f"PT{hours}H0M0S"


def _iso_dt(dt: datetime, time_str: str = WORK_START) -> str:
    return dt.strftime("%Y-%m-%d") + "T" + time_str


def build_mspdi(sched: Schedule) -> str:
    """Build MSPDI XML string for the given schedule."""
    NS = "http://schemas.microsoft.com/project"
    ET.register_namespace("", NS)
    root = ET.Element(f"{{{NS}}}Project")

    # Project header
    _add(root, "Name", sched.name, NS)
    _add(root, "Title", sched.name, NS)
    _add(root, "StartDate", _iso_dt(sched.start_date), NS)
    _add(root, "CalendarUID", "1", NS)
    _add(root, "DefaultStartTime", WORK_START, NS)
    _add(root, "DefaultFinishTime", WORK_FINISH, NS)
    _add(root, "MinutesPerDay", str(MINUTES_PER_DAY), NS)
    _add(root, "MinutesPerWeek", str(MINUTES_PER_DAY * 5), NS)
    _add(root, "DaysPerMonth", "20", NS)

    # Standard 5-day, 8-hour calendar
    cals = ET.SubElement(root, f"{{{NS}}}Calendars")
    cal = ET.SubElement(cals, f"{{{NS}}}Calendar")
    _add(cal, "UID", "1", NS)
    _add(cal, "Name", "Standard", NS)
    _add(cal, "IsBaseCalendar", "1", NS)
    _add(cal, "BaseCalendarUID", "-1", NS)
    week_days = ET.SubElement(cal, f"{{{NS}}}WeekDays")
    # Sun=1, Mon=2, ..., Sat=7 - Mon-Fri working, Sat-Sun off
    for day_type, working in [(1, False), (2, True), (3, True), (4, True),
                              (5, True), (6, True), (7, False)]:
        wd = ET.SubElement(week_days, f"{{{NS}}}WeekDay")
        _add(wd, "DayType", str(day_type), NS)
        _add(wd, "DayWorking", "1" if working else "0", NS)
        if working:
            wt = ET.SubElement(wd, f"{{{NS}}}WorkingTimes")
            morning = ET.SubElement(wt, f"{{{NS}}}WorkingTime")
            _add(morning, "FromTime", "08:00:00", NS)
            _add(morning, "ToTime", "12:00:00", NS)
            afternoon = ET.SubElement(wt, f"{{{NS}}}WorkingTime")
            _add(afternoon, "FromTime", "13:00:00", NS)
            _add(afternoon, "ToTime", "17:00:00", NS)

    # Tasks
    tasks_el = ET.SubElement(root, f"{{{NS}}}Tasks")
    for idx, t in enumerate(sched.tasks):
        _build_task(tasks_el, t, idx, NS)

    # Empty resources / assignments for completeness
    ET.SubElement(root, f"{{{NS}}}Resources")
    ET.SubElement(root, f"{{{NS}}}Assignments")

    raw = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    pretty = minidom.parseString(raw).toprettyxml(indent="  ", encoding="utf-8")
    return pretty.decode("utf-8")


def _add(parent, tag: str, text: str, ns: str):
    el = ET.SubElement(parent, f"{{{ns}}}{tag}")
    el.text = text
    return el


def _build_task(parent, t: Task, idx: int, ns: str):
    task = ET.SubElement(parent, f"{{{ns}}}Task")
    _add(task, "UID", str(t.uid), ns)
    _add(task, "ID", str(idx), ns)
    _add(task, "Name", t.name, ns)
    _add(task, "Type", "1", ns)  # 1 = Fixed Duration
    _add(task, "OutlineLevel", str(t.outline_level), ns)
    _add(task, "Priority", "500", ns)
    _add(task, "Duration", _iso_dur(t.duration_days), ns)
    _add(task, "DurationFormat", "7", ns)  # 7 = days
    _add(task, "Work", _iso_dur(t.duration_days), ns)
    _add(task, "Milestone", "1" if t.is_milestone else "0", ns)
    _add(task, "Summary", "1" if t.is_summary else "0", ns)
    _add(task, "Active", "1", ns)
    _add(task, "Manual", "0", ns)
    if t.notes:
        _add(task, "Notes", t.notes, ns)
    for pred_uid in t.predecessors:
        link = ET.SubElement(task, f"{{{ns}}}PredecessorLink")
        _add(link, "PredecessorUID", str(pred_uid), ns)
        _add(link, "Type", "1", ns)  # 1 = FS
        _add(link, "CrossProject", "0", ns)
        _add(link, "LinkLag", "0", ns)
        _add(link, "LagFormat", "7", ns)


def write_schedule(sched: Schedule, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = sched.name.lower().replace(" ", "_").replace("-", "_") + ".xml"
    path = out_dir / fname
    path.write_text(build_mspdi(sched), encoding="utf-8")
    return path
