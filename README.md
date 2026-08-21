# GO-Canada Publication Dashboard

GO-Canada operates ground-based instruments across Canada that observe space
weather. To find published research that used that data, I ran an extensive
literature search across Scopus, Google Scholar and Publish or Perish, and built
this dashboard to make the results easy to work with — filter by instrument,
year, author, journal or publisher, and view it as tables and graphs.

The dashboard also loads several other literature searches alongside mine, so
they can be compared directly: same filters, same graphs, side by side. That
makes it possible to see where different search methods agree, where they don't,
and what each one missed.

## The five databases

| Database | Papers | Checked | What it is |
|---|---|---|---|
| Main | 2,365 | 231 | My current search, the one I've worked on most |
| Library | 5,116 | 154 | Older library searches. Some Scopus queries were broken; I repaired them with minimal changes to keep the results comparable |
| John | 1,174 | 0 | A 2007–2017 database from John. Methodology isn't documented |
| John Extended | 4,962 | 122 | Extended Scopus exports, tagged by instrument from the file names |
| Recommended | 2,387 | 132 | A set of recommended queries, also tagged by instrument |

Counts as of 21 August 2026. "Checked" is the number of instrument assignments
reviewed by hand so far, with the evidence recorded; the rest are search results
awaiting review.

## Where the data lives

The live database is on Supabase. Edits made on the website save there
immediately.

Every 3 days an automatic job copies all of it into this repository as CSV
files:

| Database | Folder |
|---|---|
| Main | `data/` |
| Library | `data/databases/library/` |
| John | `data/databases/john/` |
| John Extended | `data/databases/john-extended/` |
| Recommended | `data/databases/recommended/` |

Eight CSVs per folder — papers, authors, instruments, review decisions and the
links between them. They open in Excel.

`data/LAST_BACKUP.txt` holds the date of the last successful copy. If that date
is old, the backups have stopped and someone should find out why.

## If the website stops working

Nothing is lost. Every paper, author and review decision is saved here in this
repository as spreadsheet files, and they stay here whether the website is
running or not.

To get them yourself: click the green **Code** button at the top of this page,
choose **Download ZIP**, then open any of the folders listed above. The files
open in Excel. You don't need an account, a password, or any special software.

If someone wants the website itself back, a developer can rebuild it from these
same files. What they need to set up the database is in the `docs/` folder.
