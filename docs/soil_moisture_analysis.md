# Exploratory Soil-Moisture Analysis — January 2024

## Dataset

This exploratory analysis uses the saved Open-Meteo Historical Weather API
ERA5-Land dataset for the grid cell returned nearest the requested location
(30.34° N, 76.39° E). The response coordinates are 30.300003° N,
76.399994° E. The file contains 744 hourly observations from 2024-01-01
00:00 through 2024-01-31 23:00 UTC, with no missing or duplicate timestamps
and no missing values in the four soil-moisture columns. The CSV timestamps
parse as UTC datetimes and all four layer columns parse as `float64`.

Measurements are volumetric water content in m³/m³. The layer labels are
0–7 cm, 7–28 cm, 28–100 cm, and 100–255 cm. This is one modeled grid cell over
one month, not a field sensor record.

## Descriptive statistics

Standard deviation describes the spread around the mean; here it is the sample
standard deviation (`ddof=1`) and uses the same m³/m³ units as the values. The
median is the middle hourly value. The 25th and 75th percentiles mark the lower
and upper quartiles, which contain the middle half of observations. Range is
maximum minus minimum.

| Layer | Mean | Median | Std. dev. | Min | 25th pct. | 75th pct. | Max | Range |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0–7 cm | 0.145988 | 0.145000 | 0.004999 | 0.142000 | 0.144000 | 0.147000 | 0.235000 | 0.093000 |
| 7–28 cm | 0.158469 | 0.158000 | 0.001902 | 0.155000 | 0.157000 | 0.160000 | 0.162000 | 0.007000 |
| 28–100 cm | 0.189984 | 0.190000 | 0.002633 | 0.185000 | 0.188000 | 0.192000 | 0.194000 | 0.009000 |
| 100–255 cm | 0.225487 | 0.225000 | 0.000500 | 0.225000 | 0.225000 | 0.226000 | 0.226000 | 0.001000 |

## Pearson correlation between layers

Pearson correlation summarizes how strongly two series move together in a
linear way. It ranges from -1 (opposite movement) through 0 (little linear
relationship) to +1 (strong positive linear relationship).

| Layer pair | Correlation |
|---|---:|
| 0–7 cm and 7–28 cm | 0.083 |
| 0–7 cm and 28–100 cm | 0.074 |
| 0–7 cm and 100–255 cm | 0.123 |
| 7–28 cm and 28–100 cm | 0.981 |
| 7–28 cm and 100–255 cm | 0.852 |
| 28–100 cm and 100–255 cm | 0.849 |

These correlations use all 744 hourly rows. They describe co-variation in this
month; they do not show that one layer caused changes in another. The high
correlations among deeper layers occur alongside gradual, stepwise changes,
while the surface series has a distinct late-month rise.

## Main observations

- The 0–7 cm series varies the most by both standard deviation (0.004999) and
  range (0.093000 m³/m³). The 100–255 cm series varies the least (standard
  deviation 0.000500; range 0.001000 m³/m³).
- The surface layer mostly declined through January 30, reaching its minimum
  hourly value of 0.142 at 2024-01-30 08:00 UTC. It then rose sharply during
  the final hours of January 31: 0.158 at 18:00, 0.172 at 19:00, 0.173 at
  20:00, 0.182 at 21:00, 0.209 at 22:00, and 0.235 at 23:00 UTC. The other
  three layer values remained unchanged during those hours. This peak is a
  visually isolated high value in the distribution plot and substantially
  increases the surface layer's mean, standard deviation, and range. The
  dataset alone does not explain why it occurred.
- The 7–28 cm and 28–100 cm series show the clearest shared pattern
  (correlation 0.981). Their daily means declined in small steps: 7–28 cm from
  0.162 on January 1 to 0.155 on January 31, and 28–100 cm from 0.194 to
  0.185 m³/m³.
- The 100–255 cm series was nearly constant at the recorded precision: its
  daily mean was 0.226 early in the month and 0.225 after a small step around
  January 16. Its correlation with the other deeper layers is high despite
  this small absolute variation; correlation measures co-movement, not the
  size of change.

## Visualizations

All plots are in `data/processed/soil_moisture_analysis/`:

- Plot A, all four hourly series: [soil_moisture_all_layers_jan2024.png](../data/processed/soil_moisture_analysis/soil_moisture_all_layers_jan2024.png)
- Plot B, individual series: [0–7 cm](../data/processed/soil_moisture_analysis/soil_moisture_0_7cm_jan2024.png), [7–28 cm](../data/processed/soil_moisture_analysis/soil_moisture_7_28cm_jan2024.png), [28–100 cm](../data/processed/soil_moisture_analysis/soil_moisture_28_100cm_jan2024.png), [100–255 cm](../data/processed/soil_moisture_analysis/soil_moisture_100_255cm_jan2024.png)
- Plot C, hourly distributions: [soil_moisture_layer_distributions_jan2024.png](../data/processed/soil_moisture_analysis/soil_moisture_layer_distributions_jan2024.png)

The combined time series shows that the layers have different baseline values
and different amounts of variation. The four individual plots make the
stepwise downward changes in deeper layers and the late surface-layer rise
easier to see. The box plot compares medians and middle-half spreads and makes
the surface layer's late high values stand out.

## Limitations

This is a one-month analysis of modeled ERA5-Land grid-cell values. Hourly
observations repeat many values and are rounded to three decimal places, so
the series are stepwise and some correlations can reflect shared slow trends.
The single high surface value is reported as observed; this analysis does not
infer its cause or determine whether it is an error. Pearson correlation only
describes linear association in this sample.

These measurements do not directly quantify plant-available water or crop
stress. Interpretation would require additional context, including soil
properties, crop rooting depth, crop type, growth stage, irrigation, and
validation against relevant observations. No agricultural threshold or
prediction is estimated here.
