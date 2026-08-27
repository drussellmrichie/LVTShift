# Washington DC — the Vacant/Blighted regime reaches idle buildings, not idle land

Policy finding from the DC LVT model, moved out of `CLAUDE.md` on 2026-08-27 (it was over budget): it is an
analytical result for a legal or political brief, not operating knowledge an agent needs
in order to work on the code. Statutory citations and parcel counts are as checked when
written; re-verify before quoting.

**Vacant/Blighted (Class 3/4) is an anti-abandoned-*building* regime, not an anti-idle-*land* regime —
a real loophole, confirmed in the data, not just a statutory technicality.** DC Code § 47-813(c-8)(4)/(5)
defines Class 3/4 as *improved* real property appearing on DOB's vacant/blighted building registry
(§§ 42-3131.16/.17) — bare, unimproved land is categorically outside the punitive $5-10/$100 rate,
regardless of how long it sits idle. Checked against the assessor's own `PROPTYPE` vacant-land
subtypes (`Vacant-True`, `Vacant-Zoning Limits`, `Vacant-False-Abutting`, `Vacant-Permit`,
`Vacant-Unimproved Parking`, `Vacant-Residential Use` — 11,191 parcels total): only 87 (0.8%) are
actually billed at the Class 3/4 rate. The other 99.2% are billed at the ordinary Class 1A/2 rate,
because DC's own use-code confirms they carry no structure. This is also *why* `PROPTYPE`-based
"Vacant Land" jumps so hard under the reform (+141% median at 4:1, see the model's category table) —
DC's current system is barely taxing bare land today regardless of the nominal vacant-property rate on
the books.

Registration exceptions create additional timed safe harbors an owner can lean on: active
marketing-for-sale/rent exempts a building for <1 year (residential) / <2 years (commercial); a pending
zoning/historic-preservation application (BZA, Zoning Commission, CFA, HPRB, Mayor's Agent, NCPC)
exempts it indefinitely while the application sits open; litigation/probate also exempts. Blighted
(Class 4, $10/$100) vs. merely-vacant (Class 3, $5/$100) turns on physical-condition criteria (weather-
tight/secured openings, no exterior holes/graffiti/rot) — cheap-maintenance items an owner can address
just enough to stay at the lower of the two punitive rates.

**The sharpest cliff of all: demolition.** Because Class 3/4 requires *improved* property, an owner
facing the vacant-building rate on a deteriorating structure can tear it down and immediately drop to
the ordinary, much lower unimproved-land rate — a large tax cut for producing a vacant lot instead of a
vacant building. This is a real, data-confirmed perverse incentive worth flagging in any DC-focused
legal or political brief: DC's vacant-property tax regime, as written, does not reach idle land at all,
only idle buildings, and rewards clearing the buildings away.
