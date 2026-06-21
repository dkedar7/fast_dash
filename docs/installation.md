# Installation

## Stable release

To install Fast Dash, run this command in your
terminal:

<div class="termy">

``` console
$ pip install fast-dash
```

</div>

This is the preferred method to install Fast Dash, as it will always install the most recent stable release.

If you don't have [pip][] installed, this [Python installation guide][]
can guide you through the process.

## Optional extras

The [MCP server](User%20guide/ai_agents.md) (`mcp_server=True`) works out of the
box — it is built on Dash's native MCP support, which Fast Dash installs for you.

For the **real-time WebSocket backend** (`backend="fastapi"`, which streams agent
updates to the browser via `set_props` instead of polling), install the
`fastapi` extra:

<div class="termy">

``` console
$ pip install 'fast-dash[fastapi]'
```

</div>

## From source

The source for Fast Dash can be downloaded from
the [Github repo][].

You can either clone the public repository:

<div class="termy">

``` console
$ git clone git://github.com/dkedar7/fast_dash
```

</div>

Or download the [tarball][]:

<div class="termy">

``` console
$ curl -OJL https://github.com/dkedar7/fast_dash/tarball/main
```

</div>

<div class="termy">

</div>


Once you have a copy of the source, you can install it with:


``` console
pip install .
```


  [pip]: https://pip.pypa.io
  [Python installation guide]: http://docs.python-guide.org/en/latest/starting/installation/
  [Github repo]: https://github.com/dkedar7/fast_dash
  [tarball]: https://github.com/dkedar7/fast_dash/tarball/main

