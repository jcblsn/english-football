# Page 324 brand

This directory holds the current Page 324 visual identity decisions.

`identity.json` is the machine-readable source of truth. Use it when you create site styles, chart guidance, image assets, or other visual material. Do not copy values into new files unless the build process needs a generated output.

The identity is provisional. Change `identity.json` when a decision changes.

## Direction

Page 324 is an editorial publication that uses quantitative football forecasts. It is not a software dashboard.

The visual system should feel rigorous, quantitative, trustworthy, contemporary, independent, and slightly idiosyncratic.

Use typography, spacing, rules, tables, and data as the main visual material. Avoid decorative interface chrome.

The 3-2-4 block mark can influence grid, alignment, and rhythm. Do not turn the site into a literal character grid.

## Color

The primary accent is `#FFD400`.

Use the accent as a Page 324 identity and interface color. Do not use it to mean good, bad, promotion, relegation, win, loss, or probability magnitude.

Use `#121210` for text on the accent.

Keep the Page 324 accent separate from the chart and data-visualization palette.

## Typography

Use Libre Franklin for display text, navigation, interface text, tables, and numbers.

Use Source Serif 4 for long-form article text.

Use tabular lining figures for statistical data.

Use monospaced type only for technical metadata when it has a real function. Do not use monospaced type only to make content look like data.

## Layout

Use a 12-column editorial grid.

Use an 8 px spacing unit.

Keep article prose near 720 px wide.

Allow charts and tables to use more width than prose when the data needs it.

Prefer whitespace and thin rules over cards and boxes.

## Tables and probability

Tables should be dense, calm, and easy to scan.

Do not use vertical rules by default.

Do not use zebra striping by default.

Right-align numeric values and use tabular figures.

Always show the numeric probability value. Bars can support comparison, but they must not replace the number.

## Datawrapper

Assume the Datawrapper Free plan.

The standard Datawrapper theme and Roboto are acceptable. The Page 324 site does not depend on chart typography matching the site typography.

Do not put Datawrapper charts in decorative cards.

Use chart colors, annotation rules, number formats, chart selection, and editorial practice to create consistency.

Keep Datawrapper attribution visible.

## Charts

These rules come from the first four draft charts. They are provisional. `charts/definitions.toml` holds the defined chart set, and `scripts/refresh_charts.py` writes each chart again from the latest forecast. A rule here must be one a recipe can apply every time, not a choice made once.

### Editorial voice

A chart title says what the chart measures. It does not make a claim. Write "Premier League title probability", not "Arsenal leads the title race". The claim belongs in the article.

This is not only a matter of tone. A title that makes a claim must be rewritten for every new forecast, so the chart becomes single use. A title that describes the measure lets the same chart run again against the next forecast.

For the same reason, the introduction holds only facts that stay true between forecasts. Move the current state of the season into the article.

### Order

Rank the clubs by the probability that the chart plots, before it is rounded. When two clubs have the same probability, put the club with the better expected final position first. Do not break a tie by club name, because the order then has no meaning.

Sort the rows during data extraction and keep that order. Do not let the chart tool sort, because its result for equal values is not defined.

Give the order in the introduction when the chart does not show it. A ranked bar chart shows its own order. A table does not, so its introduction says what the order is.

### Probability

A chart shows whole percentages. A table shows one decimal place, because a table is the place a reader goes for the exact value. A dense matrix shows whole percentages.

A displayed 0% means less than half of the last shown digit. It can include zero, and it never means that the result is impossible. Give the threshold in the notes. A simulated season that produces no wins for a club is not evidence that the club cannot win.

When each value is rounded on its own, a set of shares can total more or less than 100%. Do not change the values to make them add up.

Give a one-winner event a fixed 0% to 100% axis. The reader then sees the probability against its full range.

### Color

Charts are grayscale. A hue must earn its place: use one only when a chart cannot carry its meaning in grey, and say why. The greys already carry rank, so a grayscale chart is usually the clearer one.

Use near-black `#121210` for a chart with one data series, and for the value the chart is about when one value in each row matters more than the others. Do not put a track behind the bars. The bar on the white canvas is enough, and the track adds a second rectangle that means nothing.

The supporting greys, in order of weight, are `#6C6A64`, `#9E9B93` and `#D8D5CC`. Pick them so that two greys that touch are two steps apart.

A table cell scale runs white `#FFFFFF` to `#B9B5AA`. It stays light enough that the number is readable on every cell. One scale serves every colored column of a table, so color only columns that hold the same unit, and then equal ink means equal value across the whole table.

Near-black means "this is the value in question". It does not mean good, promotion or relegation.

Never use the Page 324 accent as a data color.

### Labels

Every value must be readable. A bar or a segment is never the only way to get a number.

On a stacked bar, put the row label on its own line. The bar then keeps the full width, and narrow segments keep their labels on a small screen. Without this, the chart tool drops the labels it cannot fit, and it drops them silently.

Use a color key only when it says something the chart cannot say in words. A stacked bar with a fixed series order needs one sentence in the introduction, not a key.

In a dense table, use a short club label. The full name makes the first column two lines deep and takes the width that the data needs.

### Tables

A table can carry a cell scale, in grey only. Use it where the shape of a distribution is part of the story, as in the final-position matrix, and where every colored column holds the same unit. Do not color a column that is not a probability.

In a dense table, round to whole percentages and leave a cell blank when it falls below 0.5%. A blank says "too small to matter here". A zero says "this cannot happen", which is not true. Say in the notes what a blank means.

Keep the first column fixed so the club name stays in view when a wide table scrolls sideways.

Choose the columns that appear on a small screen yourself. A table that is too wide clips its last columns rather than dropping them, so the reader silently loses the right-hand side of the table. Pick a set that fits, and keep the columns that carry the forecast rather than the ones that carry context.

Turn the mobile fallback on. A wide table then stacks each club into its own block on a small screen instead of clipping its right-hand columns. The block repeats a label for every value, so keep the small-screen set to the club and the two or three columns that carry the story.

Let readers download the full table when columns are hidden on small screens.

### Notes

The notes are short. Three sentences at the most. They record the forecast time, the public model version and the number of simulations, and then say only what the reader cannot get from the chart, such as the threshold behind a displayed zero or a blank cell.

Write the forecast time as `YYYY-MM-DD HH:MM UTC`. The forecast ID is a machine key and it does not belong in front of a reader. The time comes from that ID, so one time still names one forecast document.

The notes are not a disclaimer. A limit that applies to every Page 324 forecast belongs in the method page, not under each chart.

Every chart carries the same attribution: the source name and the byline are `Page 324`, and the source link is `https://page324.substack.com/`.

Let readers embed the chart, download the image and download the data.

### Review

Check every chart at the width it is designed for and at 320 px before you accept it. Problems with labels appear only at the small width. A normal chart is 640 px. A wide table, such as the twenty-position matrix, is 1040 px, because a Datawrapper numeric column does not go below about 45 px.

Look at the export. A count of columns, a wrapped interval and a dropped label are all invisible in the settings.

## Logo and texture

Use a clean solid version of the 3-2-4 mark at small sizes.

Use the slightly imperfect printed wordmark at larger sizes.

Texture is a signature. It is not a page-wide effect.

Do not apply the printed texture to normal headings, tables, or interface text.

## Avoid

Do not use Ceefax pastiche, pixel fonts, CRT effects, scanlines, teletext motifs, football green as the default brand color, generic SaaS styling, excessive gradients, glass effects, or decorative data motifs.

Do not make every content item a card.
