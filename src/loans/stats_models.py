"""Describes the responses and arguments to the stats endpoints. We mainly do
line charts across time.
"""
from pydantic import BaseModel
import typing


class LinePlotSeries(BaseModel):
    """Describes a single series within a line plot.

    Attributes:
    - `name (str)`: The name of the series, e.g., "Inprogress Loans"
    - `data (list[float])`: The value at each category, index-correspondence to
      the `categories` array.
    """
    name: str
    data: typing.List[float]


class LinePlotData(BaseModel):
    """Describes the data for a line plot.

    Attributes:
    - `categories (list[str])`: The name of each x-axis value. Should be equally
      separated. E.g. `['1Q14', '2Q14', '3Q14', '4Q14', '1Q15']`.
    - `series (list[LinePlotSeries])`: The series within the plot.
    """
    categories: typing.List[str]
    series: typing.List[LinePlotSeries]


class LinePlot(BaseModel):
    """Describes a complete line plot

    Attributes:
    - `title (str)`: The title for the plot
    - `x_axis (str)`: The title of the x-axis
    - `y_axis (str)`: The title of the y-axis
    - `generated_at (float)`: When this data was grabbed in unix time.
    - `data (LinePlotData)`: The data within the plot
    """
    title: str
    x_axis: str
    y_axis: str
    generated_at: float
    data: LinePlotData
