# ALPINE-WATCH
### *Sierra Nevada & Cascades · Lake Clarity Monitor*

**`bdgroves/Alpine-watch`** — automated water quality surveillance for 13 high-elevation sentinel lakes across California, Washington, and Oregon. Built to watch the slow greening of water that was never supposed to turn green.

---

> *"At an elevation of 11,135 feet, in the state's largest federally designated wilderness, this degree of algal abundance would have been unthinkable not long ago."*
>
> — Cody Cottier, *Scientific American*, April 2026

---

## What Is This

Mountain lakes at elevation are supposed to be cold, clear, and nutrient-starved. That's the baseline. That's been the baseline for millennia. But something is changing in the high country, and it's not subtle anymore.

ALPINE-WATCH is my attempt to watch it happen from a desk in Lakewood, Washington — using the same federal water quality database that academic researchers use, pulled automatically twice a week from April through October, rendered into a live dashboard at [bdgroves.github.io/Alpine-watch](https://bdgroves.github.io/Alpine-watch).

The science is being done by people like Isabella Oleksy at CU Boulder, who's spent years documenting decades-long chlorophyll-a increases in Rocky Mountain National Park lakes, and who found cyanobacteria — specifically *Dolichospermum*, carrier of the neurotoxin delightfully nicknamed "Very Fast Death Factor" — blooming in Turkey Creek Lake, Colorado, at 11,135 feet elevation. That story hit *Scientific American* this spring. It's been rattling around in my head ever since.

This is the Pacific Coast version of that watch.

---

## The Lakes

13 sentinel lakes, hand-selected across three mountain ranges:

### Sierra Nevada (California)

| Lake | Elevation | Why It Matters |
|---|---|---|
| **Lake Tahoe** | 6,225 ft | The gold standard. Tahoe's clarity record is one of the most closely watched environmental metrics in the American West. When it declines, people notice. |
| **Fallen Leaf Lake** | 6,377 ft | Tahoe-adjacent and ecologically coupled. A canary for Basin nutrient loading before it reaches the main lake. |
| **Donner Lake** | 5,936 ft | Highway 80 runoff, recreation pressure, proximity to Truckee. This one has known issues — watching for acceleration. |
| **Convict Lake** | 7,583 ft | Deep in the Eastern Sierra, benchmarked against genuine pristine conditions. |
| **Twin Lakes (Bridgeport)** | 7,000 ft | A paired comparison site — two adjacent lakes with slightly different watershed geometries. |

### Eastern Sierra

| Lake | Elevation | Why It Matters |
|---|---|---|
| **Mono Lake** | 6,383 ft | Terminal saline lake with no outflow. Water level and salinity are the primary signals here, not chlorophyll — a different kind of watch. |

### Cascades — Washington

| Lake | Elevation | Why It Matters |
|---|---|---|
| **Lake Chelan** | 1,086 ft | One of the deepest lakes in North America (1,486 ft). An exceptional clarity baseline and an early-warning system for the entire Chelan watershed. |
| **Diablo Lake** | 1,201 ft | That famous Crayola turquoise color is glacial flour in suspension — fine sediment ground from rock by Ross Lake glacier. Color shift = glacial health signal. |
| **Lake Cushman** | 738 ft | Olympic Peninsula reservoir. Lower elevation comparison site — what does "not alpine" look like on the same dataset? |
| **Spirit Lake** | 3,417 ft | USGS has monitored this lake continuously since the 1980 eruption of St. Helens. Decades of post-catastrophe recovery data. One of the most fascinating datasets in the system. |

### Cascades — Oregon

| Lake | Elevation | Why It Matters |
|---|---|---|
| **Crater Lake** | 6,178 ft | Deepest lake in the United States. **Former world clarity record holder** — Secchi depth of 142 feet recorded in 1997. NPS has maintained long-term monitoring. If Crater Lake goes cloudy, something has gone seriously wrong. |
| **Odell Lake** | 4,787 ft | High-elevation Cascade lake, oligotrophic benchmark, historically low in nutrients. |
| **Waldo Lake** | 5,414 ft | By some measures, **one of the purest lakes on earth**. Ultraoligotrophic. Almost no dissolved nutrients. The control group. |

---

## The Science

Algae need two things: light and nutrients. Mountain lakes historically had both light and essentially no nitrogen or phosphorus — that's why they're clear. The problem is that nitrogen and phosphorus are now everywhere, and they travel:

- **Car exhaust** releases nitrous oxides that oxidize to nitrate
- **Agricultural ammonia** volatilizes from fertilized fields and drifts as gas
- **Wind-blown dust** from eroded soils carries particulate phosphorus
- **Wildfires** release stored nitrogen from vegetation they consume
- **Glacial melt** exposes fresh mineral surfaces that leach phosphorus

Some of these molecules drift hundreds of miles. They settle on lake surfaces. Even at trace concentrations, phosphorus in particular can generate — as one 1974 researcher put it in *The Algal Bowl* — **500 times its own weight in living algae**.

Then climate change ties it all together: snow melts faster, lakes warm up sooner, stratification strengthens, and algae that once couldn't compete in cold water get their window.

### What ALPINE-WATCH Measures

| Metric | Unit | EPA Threshold | What It Tells You |
|---|---|---|---|
| **Chlorophyll-a** | µg/L | >10 = eutrophic | Direct measure of algal biomass |
| **Secchi depth** | meters | <3m = turbid | Visual clarity; integrates multiple effects |
| **Water temperature** | °C | — | Controls stratification timing |
| **Total phosphorus** | mg/L | >0.025 = enriched | Primary limiting nutrient |

Alert levels follow EPA National Lakes Assessment thresholds:

```
● WATCH      Oligotrophic   Chl-a < 2.5 µg/L   The way it's supposed to be
● CAUTION    Mesotrophic    Chl-a 2.5–5 µg/L    Worth watching
● ELEVATED   Upper meso     Chl-a 5–10 µg/L     Something is feeding this
● CRITICAL   Eutrophic      Chl-a > 10 µg/L     Ecosystem stress — possible cyanobacteria
```

---

## Architecture

```
USGS Water Quality Portal
        │
        ▼
scripts/fetch_lakes.py          ← pixi run fetch
  ├── WQP API queries (lat/lon bounding box per lake)
  ├── 5-year rolling window, 7 water quality characteristics
  ├── Monthly chlorophyll-a time series
  └── Alert level classification
        │
        ▼
docs/data/
  ├── lakes.json                 ← dashboard overview (all lakes)
  ├── {lake_id}.json             ← per-lake detail + timeseries
  └── manifest.json             ← run metadata
        │
        ▼
scripts/render_charts.py        ← pixi run render
  ├── Status grid (all lakes)
  ├── Chlorophyll-a comparison bar chart
  └── Per-lake sparkline PNGs
        │
        ▼
docs/charts/
  ├── status_grid.png
  ├── chlorophyll_comparison.png
  └── spark_{lake_id}.png
        │
        ▼
GitHub Actions (.github/workflows/fetch-deploy.yml)
  └── Tue + Fri 06:00 UTC → fetch → render → commit → gh-pages deploy
```

**Stack:**
- `pixi` for reproducible Python environments (no venv, no conda shenanigans)
- `requests`, `pandas`, `numpy` for data
- `matplotlib` for chart generation
- Plain HTML/CSS/JS for the dashboard (no frameworks)
- GitHub Actions for the satellite — this thing runs without me touching it all summer

**Data source:** [USGS Water Quality Portal (WQP)](https://www.waterqualitydata.us/) — the federal consolidated repository for water quality data from EPA, USGS, state agencies, and tribal programs. Real data. Publicly accessible. The same data scientists use.

---

## Setup

```powershell
# Clone
git clone https://github.com/bdgroves/Alpine-watch.git
cd Alpine-watch

# Install environment
pixi install

# Fetch lake data from WQP
pixi run fetch

# Render charts
pixi run render

# Or do both
pixi run build

# Open docs/index.html in a browser to see the dashboard
```

### GitHub Pages Deploy

1. Push to `main`
2. Go to Settings → Pages → Source: `gh-pages` branch, `/ (root)` directory
3. The Actions workflow handles everything else

The workflow fires on Tuesday and Friday at 06:00 UTC (before the workday anywhere in the U.S.). Manual trigger available under Actions → "alpine-watch · fetch & deploy" → Run workflow.

---

## Why These Lakes, Specifically

**Waldo Lake (OR, 5,414 ft)** is the control group. By most measurements, it's one of the purest lakes on the planet — essentially distilled rainwater in a bowl above tree line. No tributaries. No development. No agriculture within 50 miles. If Waldo starts showing elevated chlorophyll, there's no local explanation. That's atmospheric deposition from somewhere else. The signal would be unambiguous.

**Crater Lake (OR, 6,178 ft)** held the world Secchi depth record — 142 feet of visible water — for years. NPS has been measuring it since the 1960s. The recent trend is downward. Not catastrophically, but measurably. That's the kind of thing ALPINE-WATCH is built to track.

**Diablo Lake (WA, 1,201 ft)** is technically not "alpine" by elevation, but its color is driven by glacial flour from the Neve Glacier and other Ross Lake-area ice. That color is changing as the glaciers retreat. It's a real-time readout of a different kind of high-mountain change.

**Spirit Lake (WA, 3,417 ft)** is the wildcard. Mount St. Helens erupted in 1980, deposited a pyroclastic horror show into this lake, and USGS has been watching ever since. Forty-five years of post-catastrophe recovery data. A lake rebuilding an ecosystem from scratch. No other monitoring site in the system has a story like this one.

---

## What I'm Watching For

1. **Long-term chlorophyll-a trends** — is the baseline rising? At what rate?
2. **Early-season onset** — are blooms appearing earlier in the year than historical records suggest?
3. **Waldo anomalies** — any signal in the control group is a flag
4. **Crater Lake clarity** — Secchi depth is the headline metric here
5. **Spirit Lake trajectory** — ongoing recovery or new pressures?
6. **Paired comparisons** — Odell vs. Waldo (same range, different nutrient exposure), Tahoe vs. Fallen Leaf

---

## Roadmap

- [ ] MODIS/Aqua satellite chlorophyll retrieval via NASA Earthdata (NASA LAADS DAAC)
- [ ] Nitrogen deposition overlay from NADP (National Atmospheric Deposition Program)
- [ ] Secchi depth historical chart — decade-scale trends for Tahoe, Crater Lake
- [ ] Wildfire proximity layer — NIFC perimeters buffered to watershed boundaries
- [ ] Snowpack anomaly column from NRCS SNOTEL data
- [ ] Email/GitHub Issue alert on CRITICAL threshold breach
- [ ] Leaflet map with lake markers colored by alert level (PELE crossover aesthetic)

---

## Further Reading

- Cottier, Cody. "Why pristine mountain lakes are suddenly turning green." *Scientific American*, April 2026.
- Oleksy, Isabella et al. Long-term lake monitoring program, Rocky Mountain National Park, CU Boulder.
- Handler, Amalia et al. "Eutrophication of mountain lakes across the continental U.S." *Limnology and Oceanography*, 2025.
- Vallentyne, J.R. *The Algal Bowl.* Dept. of the Environment, Ottawa, 1974.
- [USGS Water Quality Portal](https://www.waterqualitydata.us/)
- [EPA National Lakes Assessment](https://www.epa.gov/national-aquatic-resource-surveys/nla)
- [NPS Crater Lake Water Quality Monitoring](https://www.nps.gov/crla/learn/nature/water.htm)

---

## Related Projects

| Project | What |
|---|---|
| [**PELE**](https://brooksgroves.com) | Kīlauea eruption dashboard · SO₂, lava flow, USGS volcano data |
| [**EDGAR**](https://bdgroves.github.io/EDGAR) | MLB analytics · Mariners & Rainiers · pybaseball + nightly Actions |
| [**sierra-streamflow**](https://bdgroves.github.io/sierra-streamflow) | USGS gage monitoring across Tuolumne, Merced, Stanislaus, Big Creek |
| [**SIERRA-FLOW**](https://github.com/bdgroves/SIERRA-FLOW) | GnuCOBOL streamflow dashboard · green phosphor aesthetic |
| [**CASCADIA-WX**](https://github.com/bdgroves/CASCADIA-WX) | FORTRAN PNW mountain weather · amber phosphor |
| [**AFTERSHOCK**](https://github.com/bdgroves) | USGS seismic monitor · Pacific Northwest focus |
| [**RIDGELINE**](https://bdgroves.github.io/ridgeline) | WUI search-and-rescue call volume analysis · Phoenix Fire Dept |
| [**project-kiva**](https://github.com/bdgroves/project-kiva) | Southwest archaeology remote sensing · LiDAR + R/rayshader |

---

*Brooks Groves · Lakewood, WA · [brooksgroves.com](https://brooksgroves.com)*

*Built while following the 2026 monitoring season — and thinking about what those mountain lakes looked like when nobody was measuring them.*
