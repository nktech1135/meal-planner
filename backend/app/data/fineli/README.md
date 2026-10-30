# Fineli open data, Release 20 (vendored)

`fineli_rel20_74_components.zip` is Fineli's open-data "Basic package 2" (4,232 foods, 74 food components),
Release 20.0, files dated 2019-08-08, unchanged. It is a superset of "Basic package 1" (55 components, the content
of the Fineli website): the same foods and files, with 19 more components (including CHOCDF, carbohydrate by
difference).

- Publisher: Finnish Institute for Health and Welfare (THL), Fineli. "Fineli" is a registered trademark of THL.
- Licence: Creative Commons Attribution 4.0 (CC BY 4.0), https://creativecommons.org/licenses/by/4.0/
- Attribution: Finnish Institute for Health and Welfare, Fineli.
- Open data page: https://fineli.fi/fineli/en/avoin-data (package link https://fineli.fi/fineli/content/file/49,
  which redirects to `.../file/49/Fineli_Rel20__74_ravintotekij__`).
- SHA-256: `e7e6bd8d4b9261d751229e763dad436b297d36d48fe853faf49e1fd2a116d262` (1,954,388 bytes)

Why it is bundled: fineli.fi answers scripted requests (including the package URL and the JSON API) with a
Cloudflare browser challenge (HTTP 403), and no other official mirror exists (the national catalogue
avoindata.suomi.fi only links to THL's site). The copy was retrieved on 2026-10-30 from the Internet Archive's
capture of the package URL (2022-08-01); the open-data page still listed the same package (same size and food
count) in its 2026-10-12 capture. THL's copyright and disclaimer are in `descript.txt` inside the zip.

Parsed by `app/sources/intl/fineli.py`.
