# Right-to-Know Law requests

Drafted 2026-09-21 for the Scranton split-rate repeal analysis (`analysis/scranton_repeal/`).
Request 1 was sent 2026-09-21 (see `rtk_tracker.csv` for status). Request 2 has not been sent.
The 2025 side is already covered by public data: pre-reassessment
land and building values from the County's public GIS layer (`GISViewer/LandRecords/MapServer/85`)
reproduce the 2025 City levy stated in the 2026 rate ordinance (File of the Council No. 107,
2025). The one record the analysis cannot proceed without is the **2026 certified roll**
(request 1). The 2026 rate is also settled: the ordinance, adopted 2025-12-16, sets it at
6.35095037123 mills on the 2025-11-14 certified roll. Request 2 is optional. It would give
billed amounts, so bill C could be checked parcel by parcel rather than only in total.

Before filing, it may be worth one informal call or email to the Lackawanna County
Assessor's Office or County GIS asking whether a parcel-level export of the 2026 roll already
exists for release. Counties often hand one over without a formal request. A formal RTKL
request fixes the response clock (5 business days, extendable by 30) and gives a right of
appeal to the Office of Open Records.

---

## Request 1: Lackawanna County

*As sent on 2026-09-21, the request differs from the draft below in two ways: the 2025 roll
is requested outright as item 1(c), and the purpose sentence is omitted. The text as sent is
in `rtk_outbox/` (git-ignored, because it carries the requester's address).*

**To:** Traci Harte, Deputy Chief of Staff / Right-to-Know Officer, Lackawanna County
Government Center, 123 Wyoming Avenue, 6th Floor, Scranton, PA 18503.
hartet@lackawannacounty.org · 570-963-6800. The County accepts its own online form and the
standard OOR Uniform Request Form
(https://www.lackawannacounty.org/how_do_i/submit_a_right_to_know_request.php).

**Records requested** (Pennsylvania Right-to-Know Law, 65 P.S. § 67.101 et seq.):

1. An electronic export, as CSV or Excel or whatever electronic format the Assessment
   Office's iasWorld system already produces, of the real property assessment roll for every
   parcel in the **City of Scranton**, in two versions:
   a. the roll **certified on or about November 14, 2025 for tax year 2026** (reassessed
      values), as certified to the City of Scranton for 2026 billing;
   b. the roll as it currently stands, if it differs from (a) because of court appeals or
      other changes after certification.
   (Optional, useful as a cross-check: the same fields from the roll certified for tax
   year 2025.)

   For each parcel, the following fields, where they are maintained:
   - parcel identifier (PIN and map/parcel number);
   - municipality and school district;
   - property class / land-use code, and its code table;
   - **land** assessed value, **building (improvement)** assessed value, and total assessed
     value;
   - exempt value and exemption code (full and partial), and taxable value;
   - homestead / farmstead exclusion approval status (Taxpayer Relief Act / Homestead
     Property Exclusion Program), and the year approved;
   - property (situs) address;
   - owner name and owner mailing address;
   - lot size / acreage;
   - whether an informal review, Board appeal or Court of Common Pleas appeal was filed, its status or
     decision, its decision date, and the values before and after the appeal.

2. The **certified total** of taxable assessed value that the County certified to the City of
   Scranton for tax year 2026, and any revised or supplemental certification issued after it.

3. The code tables (data dictionary) needed to read the fields above.

I request electronic copies, delivered by email or download link. This is a request for data
held in an existing database, not for the creation of a new record. If any field is withheld,
please release the rest and cite the exemption that applies to the withheld field.

The purpose is non-commercial public-policy research. (The RTKL does not require a requester
to state a purpose; include this sentence only if it helps.)

---

## Request 2 (optional): City of Scranton

**To:** City of Scranton Open Records Officer, 340 N. Washington Ave., Scranton, PA 18503.
rtk@scrantonpa.gov · 570-348-4100 ext. 9409
(https://scrantonpa.gov/services/right-to-know-request/).
*Check the mailing address against the City's current RTKL page before sending. Search
results gave 348 N. Washington Ave; City Hall is generally listed at 340.*

**Records requested:**

1. The City of Scranton **real estate tax duplicates for tax years 2025 and 2026**, as
   electronic files. Per parcel: parcel identifier, land assessment, building assessment,
   the millage(s) applied, the face amount of the City real estate tax, any homestead or other
   exclusion applied to the City levy, and the refuse fee billed. If the Scranton Single Tax
   Office holds the duplicates on the City's behalf, please treat this request as covering
   the records it holds for the City.
2. The records supporting the 2025 City levy total of $37,202,775.59 stated in File of the
   Council No. 107, 2025, and the correction from the $36,365,628.37 stated in the draft
   ordinance withdrawn on November 25, 2025.
3. Any ordinance, resolution or other record that establishes a homestead or farmstead
   exclusion on the City real estate tax for 2025 or 2026. (The RTKL covers records, not
   questions. If no such record exists, the City's answer that none exists settles the
   point.)

Electronic copies requested, as above.

---

## What each record is for

| Record | Used for |
|---|---|
| 2026 certified roll, land and building | Bills B (2026 split-rate counterfactual) and C (2026 actual) |
| 2025 certified roll (optional) | Cross-check of the public GIS values already used for bill A |
| Class code, exemption code | Property-class breakdown; dropping exempt parcels |
| Homestead approval; owner mailing address | Owner-occupancy flag (either one; both allow a cross-check) |
| Appeal status and post-appeal values | Using values as certified at billing; flagging open appeals |
| 2025 and 2026 tax duplicates | Parcel-level check that A and C reproduce what was billed |
| City homestead answer | Whether bills B and C need a City homestead exclusion |
