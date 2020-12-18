# -*- coding: utf-8 -*-

"""
gspread_dataframe
~~~~~~~~~~~~~~~~~

This module contains functions to retrieve a gspread worksheet as a
`pandas.DataFrame`, and to set the contents of a worksheet
using a `pandas.DataFrame`. To use these functions, have
Pandas 0.14.0 or greater installed.
"""
from gspread.utils import fill_gaps
from gspread.models import Cell
import pandas as pd
from pandas.io.parsers import TextParser
import logging
import re
from numbers import Real
from six import string_types, ensure_text

try:
    from collections.abc import defaultdict
except ImportError:
    from collections import defaultdict
try:
    from itertools import chain, zip_longest
except ImportError:
    from itertools import chain, izip_longest as zip_longest

logger = logging.getLogger(__name__)

# pandas version check

major, minor = tuple(
    [int(i) for i in re.search(r"^(\d+)\.(\d+)\..+$", pd.__version__).groups()]
)
if (major, minor) < (0, 14):
    raise ImportError(
        "pandas version too old (<0.14.0) to support gspread_dataframe"
    )
logger.debug(
    "Imported satisfactory (>=0.14.0) Pandas module: %s", pd.__version__
)

__all__ = ("set_with_dataframe", "get_as_dataframe")


def _escaped_string(value, string_escaping):
    if value in (None, ""):
        return ""
    if string_escaping == "default":
        if value.startswith("'"):
            return "'%s" % value
    elif string_escaping == "off":
        return value
    elif string_escaping == "full":
        return "'%s" % value
    elif callable(string_escaping):
        if string_escaping(value):
            return "'%s" % value
    else:
        raise ValueError(
            "string_escaping parameter must be one of: "
            "'default', 'off', 'full', any callable taking one parameter"
        )
    return value


def _cellrepr(value, allow_formulas, string_escaping):
    """
    Get a string representation of dataframe value.

    :param :value: the value to represent
    :param :allow_formulas: if True, allow values starting with '='
            to be interpreted as formulas; otherwise, escape
            them with an apostrophe to avoid formula interpretation.
    """
    if pd.isnull(value) is True:
        return ""
    if isinstance(value, Real):
        return value
    if not isinstance(value, string_types):
        value = str(value)

    value = ensure_text(value, encoding='utf-8')

    if (not allow_formulas) and value.startswith("="):
        return "'%s" % value
    else:
        return _escaped_string(value, string_escaping)


def _resize_to_minimum(worksheet, rows=None, cols=None):
    """
    Resize the worksheet to guarantee a minimum size, either in rows,
    or columns, or both.

    Both rows and cols are optional.
    """
    # get the current size
    current_cols, current_rows = (worksheet.col_count, worksheet.row_count)
    if rows is not None and rows <= current_rows:
        rows = None
    if cols is not None and cols <= current_cols:
        cols = None

    if cols is not None or rows is not None:
        worksheet.resize(rows, cols)


def _get_all_values(worksheet, evaluate_formulas):
    data = worksheet.spreadsheet.values_get(
        worksheet.title,
        params={
            "valueRenderOption": (
                "UNFORMATTED_VALUE" if evaluate_formulas else "FORMULA"
            ),
            "dateTimeRenderOption": "FORMATTED_STRING",
        },
    )
    (row_offset, column_offset) = (1, 1)
    (last_row, last_column) = (worksheet.row_count, worksheet.col_count)
    values = data.get("values", [])

    rect_values = fill_gaps(
        values,
        rows=last_row - row_offset + 1,
        cols=last_column - column_offset + 1,
    )

    cells = [
        Cell(row=i + row_offset, col=j + column_offset, value=value)
        for i, row in enumerate(rect_values)
        for j, value in enumerate(row)
    ]

    # defaultdicts fill in gaps for empty rows/cells not returned by gdocs
    rows = defaultdict(lambda: defaultdict(str))
    for cell in cells:
        row = rows.setdefault(int(cell.row), defaultdict(str))
        row[cell.col] = cell.value

    if not rows:
        return []

    all_row_keys = chain.from_iterable(row.keys() for row in rows.values())
    rect_cols = range(1, max(all_row_keys) + 1)
    rect_rows = range(1, max(rows.keys()) + 1)

    return [[rows[i][j] for j in rect_cols] for i in rect_rows]


def get_as_dataframe(worksheet, evaluate_formulas=False, **options):
    r"""
    Returns the worksheet contents as a DataFrame.

    :param worksheet: the worksheet.
    :param evaluate_formulas: if True, get the value of a cell after
            formula evaluation; otherwise get the formula itself if present.
            Defaults to False.
    :param \*\*options: all the options for pandas.io.parsers.TextParser,
            according to the version of pandas that is installed.
            (Note: TextParser supports only the default 'python' parser engine,
            not the C engine.)
    :returns: pandas.DataFrame
    """
    all_values = _get_all_values(worksheet, evaluate_formulas)
    return TextParser(all_values, **options).read(options.get("nrows", None))


def _determine_index_column_size(index):
    if hasattr(index, "levshape"):
        return len(index.levshape)
    return 1


def _determine_column_header_size(columns):
    if hasattr(columns, "levshape"):
        return len(columns.levshape)
    return 1


def set_with_dataframe(worksheet,
                       dataframe,
                       row=1,
                       col=1,
                       include_index=False,
                       include_column_header=True,
                       resize=False,
                       allow_formulas=True,
                       string_escaping='default'):
    """
    Sets the values of a given DataFrame, anchoring its upper-left corner
    at (row, col). (Default is row 1, column 1.)

    :param worksheet: the gspread worksheet to set with content of DataFrame.
    :param dataframe: the DataFrame.
    :param include_index: if True, include the DataFrame's index as an
            additional column. Defaults to False.
    :param include_column_header: if True, add a header row or rows before data with
            column names. (If include_index is True, the index's name(s) will be
            used as its columns' headers.) Defaults to True.
    :param resize: if True, changes the worksheet's size to match the shape
            of the provided DataFrame. If False, worksheet will only be
            resized as necessary to contain the DataFrame contents.
            Defaults to False.
    :param allow_formulas: if True, interprets `=foo` as a formula in
            cell values; otherwise all text beginning with `=` is escaped
            to avoid its interpretation as a formula. Defaults to True.
    :param string_escaping: determines when string values are escaped as text literals
            (by adding an initial `'` character) in requests to Sheets API. 
            Four parameter values are accepted:
              - 'default': only escape strings starting with a literal `'` character
              - 'off': escape nothing; cell values starting with a `'` will be interpreted by 
                       sheets as an escape character followed by a text literal.
              - 'full': escape all string values
              - any callable object: will be called once for each cell's string value;
                     if return value is true, string will be escaped with preceding `'`
                     (A useful technique is to pass a regular expression bound method, e.g. 
                    `re.compile(r'^my_regex_.*$').search`.)
            The escaping done when allow_formulas=False (escaping string values beginning with `=`)
            is unaffected by this parameter's value. 
            Default value is `'default'`.
    """
    # x_pos, y_pos refers to the position of data rows only,
    # excluding any header rows in the google sheet.
    # If header-related params are True, the values are adjusted
    # to allow space for the headers.

    updates = []

    if include_column_header:
        elts = list(dataframe.columns)
            
        if include_index:
            if hasattr(dataframe.index, 'names'):
                index_elts = dataframe.index.names
            else:
                index_elts = dataframe.index.name
            if not isinstance(index_elts, (list, tuple)):
                index_elts = [ index_elts ]
            elts = list(index_elts) + elts
        for idx, val in enumerate(elts):
            updates.append(
                (row,
                    col+idx,
                    _cellrepr(val, allow_formulas, string_escaping))
            )
        row += 1

    values = []
    for value_row, index_value in zip_longest(dataframe.values, dataframe.index):
        if include_index:
            if not isinstance(index_value, (list, tuple)):
                index_value = [ index_value ]
            value_row = list(index_value) + list(value_row)
        values.append(value_row)
    for y_idx, value_row in enumerate(values):
        for x_idx, cell_value in enumerate(value_row):
            updates.append(
                (y_idx+row,
                 x_idx+col,
                 _cellrepr(cell_value, allow_formulas, string_escaping))
            )

    if not updates:
        logger.debug("No updates to perform on worksheet.")
        return

    cells_to_update = [ Cell(row, col, value) for row, col, value in updates ]
    logger.debug("%d cell updates to send", len(cells_to_update))

    resp = worksheet.update_cells(cells_to_update, value_input_option='USER_ENTERED')
    logger.debug("Cell update response: %s", resp)
    
def set_with_dataframes(worksheet,
                       dataframe_list,
                       row_list=1,
                       col=1,
                       include_index=False,
                       include_column_header=True,
                       resize=False,
                       allow_formulas=True,
                       string_escaping='default'):
    """
    Sets the values of a given DataFrame, anchoring its upper-left corner
    at (row, col). (Default is row 1, column 1.)

    :param worksheet: the gspread worksheet to set with content of DataFrame.
    :param dataframe: the DataFrame.
    :param include_index: if True, include the DataFrame's index as an
            additional column. Defaults to False.
    :param include_column_header: if True, add a header row or rows before data with
            column names. (If include_index is True, the index's name(s) will be
            used as its columns' headers.) Defaults to True.
    :param resize: if True, changes the worksheet's size to match the shape
            of the provided DataFrame. If False, worksheet will only be
            resized as necessary to contain the DataFrame contents.
            Defaults to False.
    :param allow_formulas: if True, interprets `=foo` as a formula in
            cell values; otherwise all text beginning with `=` is escaped
            to avoid its interpretation as a formula. Defaults to True.
    :param string_escaping: determines when string values are escaped as text literals
            (by adding an initial `'` character) in requests to Sheets API. 
            Four parameter values are accepted:
              - 'default': only escape strings starting with a literal `'` character
              - 'off': escape nothing; cell values starting with a `'` will be interpreted by 
                       sheets as an escape character followed by a text literal.
              - 'full': escape all string values
              - any callable object: will be called once for each cell's string value;
                     if return value is true, string will be escaped with preceding `'`
                     (A useful technique is to pass a regular expression bound method, e.g. 
                    `re.compile(r'^my_regex_.*$').search`.)
            The escaping done when allow_formulas=False (escaping string values beginning with `=`)
            is unaffected by this parameter's value. 
            Default value is `'default'`.
    """
    # x_pos, y_pos refers to the position of data rows only,
    # excluding any header rows in the google sheet.
    # If header-related params are True, the values are adjusted
    # to allow space for the headers.
    updates = []
    for dataframe, row in zip(dataframe_list, row_list):
        elts = list(dataframe.columns)
            
        if include_index:
            if hasattr(dataframe.index, 'names'):
                index_elts = dataframe.index.names
            else:
                index_elts = dataframe.index.name
            if not isinstance(index_elts, (list, tuple)):
                index_elts = [ index_elts ]
            elts = list(index_elts) + elts
        for idx, val in enumerate(elts):
            updates.append(
                (row,
                    col+idx,
                    _cellrepr(val, allow_formulas, string_escaping))
            )
        row += 1

        values = []
        for value_row, index_value in zip_longest(dataframe.values, dataframe.index):
            if include_index:
                if not isinstance(index_value, (list, tuple)):
                    index_value = [ index_value ]
                value_row = list(index_value) + list(value_row)
            values.append(value_row)
        for y_idx, value_row in enumerate(values):
            for x_idx, cell_value in enumerate(value_row):
                updates.append(
                    (y_idx+row,
                    x_idx+col,
                    _cellrepr(cell_value, allow_formulas, string_escaping))
                )

    if not updates:
        logger.debug("No updates to perform on worksheet.")
        return

    cells_to_update = [ Cell(row, col, value) for row, col, value in updates ]
    logger.debug("%d cell updates to send", len(cells_to_update))

    resp = worksheet.update_cells(cells_to_update, value_input_option='USER_ENTERED')
    logger.debug("Cell update response: %s", resp)

