# Google Form → Lead Notification Setup

Google Forms has no native webhook, so a small Apps Script bound to the form's
response Sheet forwards each new submission to `/webhook/form-submit`. This is
a one-time manual setup per form (or once if all shoot forms share one
response Sheet — check with whoever manages the Drive folder).

## Setup steps

1. Open the Google Form's **linked response Spreadsheet** (Responses tab →
   green Sheets icon; link one if it isn't already).
2. **Extensions → Apps Script**.
3. Delete any placeholder code and paste the script below.
4. Click the clock icon (**Triggers**) in the left sidebar → **Add Trigger**:
   - Function: `onFormSubmit`
   - Event source: `From spreadsheet`
   - Event type: `On form submit`
   - Save — Google will ask you to authorize the script (approve it).
5. Submit a test response on the live form and confirm a lead shows up at
   `/leads` and both Dean and Pat get a Line notification.

## Script

```javascript
function onFormSubmit(e) {
  var answers = {};
  var namedValues = e.namedValues;
  for (var question in namedValues) {
    answers[question] = namedValues[question][0];
  }

  // Use e.source, not SpreadsheetApp.getActiveSpreadsheet() — the latter
  // returns null for a standalone script's trigger (only works when the
  // script is bound to the sheet it's running in), which throws
  // "Cannot read properties of null (reading 'getName')".
  var formTitle = e.source.getName();

  var payload = {
    form_title: formTitle,
    answers: answers
  };

  var options = {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  };

  var url = "https://pana-studio-bot.onrender.com/webhook/form-submit?token=pana2025studioautomationsecretkey";
  UrlFetchApp.fetch(url, options);
}
```

## Notes

- The `token` query param must match the app's `SECRET_KEY` env var (currently
  `pana2025studioautomationsecretkey` per project config — if that's ever
  rotated on Render, update it here too, or the webhook will 403).
- `handlers/form_handler.py`'s `_first()` matches question titles loosely
  (substring match against a few known phrasings), so minor wording changes to
  form questions won't break it — but if a question is renamed drastically,
  double-check the lead still captures name/phone/brand/product correctly.
- If this form's response Sheet is duplicated for future shoots, the trigger
  does **not** carry over automatically — repeat step 4 for each new response
  Sheet, or better, keep reusing one shared response Sheet across shoots if
  your workflow allows it.
- When checking the **Executions** tab to debug a failure, check the **Type**
  column — clicking ▶ Run in the editor logs as `Editor` and always fails
  with "Cannot read properties of undefined (reading 'namedValues')" since
  there's no real form data to pass in; that's expected and not a bug. Only
  `Type: Trigger` entries (from an actual form submission) reflect real
  errors worth debugging.
