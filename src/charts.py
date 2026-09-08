"""Chart selection and rendering with Plotly.

The chart type comes from the analysis result (which in turn comes from the
plan), so the visualisation always matches the operation that was actually
performed.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from .analysis import AnalysisResult

# Matches the web client's design tokens: jade lead, then a restrained,
# colour-blind-safe qualitative ramp for multi-series charts.
PALETTE = ["#127d6e", "#1d6fa5", "#b4721a", "#7a4fbd", "#b4432f", "#0e8f8f", "#5f8c1f", "#a8317f"]

LAYOUT = dict(
    template="plotly_white",
    margin=dict(l=10, r=10, t=48, b=10),
    height=420,
    font=dict(family="Inter, Segoe UI, sans-serif", size=13),
    hoverlabel=dict(font_size=13),
)


def _style(fig: go.Figure, title: str) -> go.Figure:
    fig.update_layout(title=dict(text=title, x=0.01, font=dict(size=16)), **LAYOUT)
    fig.update_layout(colorway=PALETTE)
    return fig


def build_chart(result: AnalysisResult, raw_df: pd.DataFrame | None = None) -> go.Figure | None:
    """Return a Plotly figure for an AnalysisResult, or None if a chart adds nothing."""
    table = result.table
    if table is None or table.empty:
        return None

    chart = result.chart_type
    value = result.value_column
    label = result.label_column
    plan = result.plan

    try:
        if chart == "kpi":
            return None  # rendered as a metric card instead

        if chart == "line":
            return _line_chart(result)

        if chart in ("bar", "grouped_bar"):
            return _bar_chart(result)

        if chart == "pie":
            if value and label and len(table) <= 12:
                fig = px.pie(table, names=label, values=value, hole=0.45)
                fig.update_traces(textposition="inside", textinfo="percent+label")
                return _style(fig, f"{value} by {label}")
            return _bar_chart(result)

        if chart == "histogram":
            column = result.evidence.get("raw_series_column") or plan.metric
            if raw_df is not None and column in raw_df.columns:
                fig = px.histogram(raw_df.dropna(subset=[column]), x=column, nbins=40)
                fig.update_traces(marker_color=PALETTE[0])
                return _style(fig, f"Distribution of {column}")
            return None

        if chart == "box":
            column = result.evidence.get("raw_series_column") or plan.metric
            if raw_df is not None and column in raw_df.columns:
                by = plan.dimensions[0] if plan.dimensions else None
                fig = px.box(raw_df, y=column, x=by, points="outliers")
                return _style(fig, f"Spread of {column}" + (f" by {by}" if by else ""))
            return None

        if chart == "scatter":
            x, y = plan.metric, plan.second_metric
            if x in table.columns and y in table.columns:
                colour = plan.dimensions[0] if plan.dimensions and plan.dimensions[0] in table.columns else None
                fig = px.scatter(table, x=x, y=y, color=colour, opacity=0.6, trendline=None)
                fig.update_traces(marker=dict(size=7))
                return _style(fig, f"{y} vs {x}")
            return None

        if chart == "heatmap":
            frame = table.set_index(table.columns[0])
            numeric = frame.select_dtypes("number")
            if numeric.empty:
                return None
            fig = px.imshow(
                numeric,
                text_auto=True,
                aspect="auto",
                color_continuous_scale="RdBu_r",
                zmin=-1,
                zmax=1,
            )
            return _style(fig, "Correlation matrix")

    except Exception:  # noqa: BLE001 - a failed chart must never break the answer
        return None

    return None


def _bar_chart(result: AnalysisResult) -> go.Figure | None:
    table, value, label = result.table, result.value_column, result.label_column
    if not value or not label or value not in table.columns or label not in table.columns:
        return None

    dims = result.plan.dimensions
    colour = dims[1] if len(dims) > 1 and dims[1] in table.columns else None

    plot = table.head(30).copy()
    plot[label] = plot[label].astype(str)
    horizontal = plot[label].str.len().max() > 14 and len(plot) > 5

    if horizontal:
        plot = plot.iloc[::-1]
        fig = px.bar(plot, x=value, y=label, color=colour, orientation="h", text=value)
    else:
        fig = px.bar(plot, x=label, y=value, color=colour, text=value)

    fig.update_traces(texttemplate="%{text:.4~s}", textposition="outside", cliponaxis=False)
    if colour is None:
        fig.update_traces(marker_color=PALETTE[0])
    title = f"{value} by {label}" + (f" and {colour}" if colour else "")
    fig = _style(fig, title)
    if horizontal:
        fig.update_layout(height=max(380, 26 * len(plot) + 120))
    return fig


def _line_chart(result: AnalysisResult) -> go.Figure | None:
    table, value, label = result.table, result.value_column, result.label_column
    if not value or not label or value not in table.columns:
        return None
    dims = result.plan.dimensions
    colour = dims[0] if dims and dims[0] in table.columns else None

    fig = px.line(table, x=label, y=value, color=colour, markers=len(table) <= 40)
    if colour is None:
        fig.update_traces(line=dict(color=PALETTE[0], width=2.5))
    fig = _style(fig, f"{value} over time")
    fig.update_xaxes(title=label)
    return fig


def kpi_sparkline(series: pd.Series) -> go.Figure:
    """Tiny inline trend line for a KPI card."""
    fig = go.Figure(
        go.Scatter(
            y=series.values,
            mode="lines",
            line=dict(color=PALETTE[0], width=2),
            fill="tozeroy",
            fillcolor="rgba(18,125,110,0.14)",
            hoverinfo="skip",
        )
    )
    fig.update_layout(
        height=60,
        margin=dict(l=0, r=0, t=0, b=0),
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        template="plotly_white",
        showlegend=False,
    )
    return fig


def missing_values_chart(df: pd.DataFrame) -> go.Figure | None:
    missing = (df.isna().mean() * 100).round(2)
    missing = missing[missing > 0].sort_values(ascending=True)
    if missing.empty:
        return None
    fig = px.bar(x=missing.values, y=missing.index, orientation="h", text=missing.values)
    fig.update_traces(marker_color="#b4432f", texttemplate="%{text:.1f}%", textposition="outside")
    fig = _style(fig, "Missing values by column (%)")
    fig.update_layout(height=max(280, 26 * len(missing) + 120), xaxis_title="% missing", yaxis_title="")
    return fig


def overview_trend_chart(df: pd.DataFrame, metric: str, date_column: str) -> go.Figure | None:
    working = df[[date_column, metric]].dropna()
    if working.empty:
        return None
    series = working.set_index(date_column)[metric].resample("MS").sum()
    if len(series) < 2:
        return None
    frame = series.reset_index()
    frame.columns = [date_column, metric]
    fig = px.area(frame, x=date_column, y=metric)
    fig.update_traces(line=dict(color=PALETTE[0], width=2.5), fillcolor="rgba(18,125,110,0.14)")
    return _style(fig, f"Monthly {metric}")


def top_categories_chart(df: pd.DataFrame, metric: str, dimension: str, limit: int = 10) -> go.Figure | None:
    working = df[[dimension, metric]].dropna()
    if working.empty:
        return None
    series = working.groupby(dimension)[metric].sum().sort_values(ascending=False).head(limit)
    if series.empty:
        return None
    frame = series.iloc[::-1].reset_index()
    frame.columns = [dimension, metric]
    fig = px.bar(frame, x=metric, y=dimension, orientation="h", text=metric)
    fig.update_traces(marker_color=PALETTE[0], texttemplate="%{text:.4~s}", textposition="outside", cliponaxis=False)
    fig = _style(fig, f"Top {limit} {dimension} by {metric}")
    fig.update_layout(height=max(320, 28 * len(frame) + 120))
    return fig


def correlation_heatmap(matrix: pd.DataFrame) -> go.Figure | None:
    if matrix is None or matrix.empty:
        return None
    fig = px.imshow(
        matrix, text_auto=True, aspect="auto", color_continuous_scale="RdBu_r", zmin=-1, zmax=1
    )
    return _style(fig, "Correlation between metrics")


def distribution_chart(df: pd.DataFrame, column: str) -> go.Figure | None:
    series = df[column].dropna()
    if series.empty or not np.issubdtype(series.dtype, np.number):
        return None
    fig = px.histogram(series, x=column, nbins=40)
    fig.update_traces(marker_color=PALETTE[0])
    return _style(fig, f"Distribution of {column}")
