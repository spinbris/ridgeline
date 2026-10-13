"""Integrated cost+schedule MC engine (SR8, SP21).

This package orchestrates the cost engine (src/) and the schedule engine
(src/sra/) into a single joint-sampled Monte Carlo simulation. Per-risk
shared uniforms drive both cost and schedule severity for the 8 dual-coded
(Time=Yes) risks, producing correlated per-risk severities. All 25 cost-only
Open risks use independent uniforms.

Pure-data layer. No HTML rendering. The integrated_runner.ipynb notebook is
the presentation layer.
"""
