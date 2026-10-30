"""Problems the evaluation found and what changed, with the measurement before and after.
The full table, with how each was found, is in IMPROVEMENTS.md; the app's evaluation page shows these."""

FIXES = [
    {"what": "Forecast follows a change in sales within a week", "before": "26.4%", "after": "20.8%",
     "measure": "Error on real U Walk sales, last 6 weeks"},
    {"what": "Invoices always matched to your ingredients", "before": "4 of 21", "after": "0",
     "measure": "Invoice reads that lost their ingredient matches"},
    {"what": "Claude's stock notes quote only real numbers", "before": "2", "after": "0",
     "measure": "Numbers in the notes that are not on the order"},
    {"what": "An odd answer from Claude no longer breaks an agent", "before": "error", "after": "rules",
     "measure": "Answer of the wrong shape: the rules take over"},
    {"what": "A slow Claude can't freeze the cashier", "before": "10 min", "after": "30 s",
     "measure": "Longest wait before the rules answer instead"},
    {"what": "Bad sales files are refused before stock changes", "before": "error", "after": "clear reason",
     "measure": "A quantity like \"two\" or \"-3\" in a POS report"},
    {"what": "Dishes with no recipe are flagged", "before": "silent", "after": "warned",
     "measure": "Their sales would never reduce stock"},
]
