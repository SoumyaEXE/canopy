# What this tool cannot do

**Merged crowns.** In closed canopy, adjacent trees touching each other are often detected as one crown. This causes undercounting, and it is the main source of error in dense forest.

**Understory invisibility.** Anything growing beneath the canopy is not visible from above and is not counted. In multi-layer forest this can be a large fraction of all stems.

**Vegetation is not trees.** With RGB imagery there is no reliable way to distinguish a tree from a tall hedge, a green roof, a crop field, or a shrub. The tool counts green blobs of roughly tree size.

**No species, no age, no health.** These require spectral bands, ground survey, or both.

**Imagery date is often unknown.** Basemap tiles carry no reliable acquisition date. The forest may have changed since capture.

**Shadow heights are geometric estimates.** They assume flat terrain and an unobstructed shadow. On slopes and in dense canopy they are unreliable, which is why they are only reported for crowns passing the quality gate. The visible shadow is measured from the crown edge, so heights are biased low by roughly one crown radius times the tangent of the sun elevation.

**Threshold sensitivity.** Move the threshold slider and watch every number change. The tool reports the result of a choice, not a ground truth.

**No carbon estimate.** Converting crown area to biomass requires species-specific allometric equations, wood density values, local calibration plots, and a root-to-shoot ratio. This tool has none of these, so it does not output tonnes of CO2, biomass, or credit figures, not even roughly.
