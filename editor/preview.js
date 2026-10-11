// Added to the PDF.js viewer by preview.py, which calls these two functions:
// the live preview swaps in each rebuilt PDF without losing the reader's
// place, and highlights the text of the field being edited.
(() => {
  "use strict";
  const NOT_FOUND = 1, PENDING = 3; // PDF.js FindState
  let latest = 0; // only the most recent highlight request finishes

  // Resolves with the next `name` event on the viewer's event bus that
  // `accept` approves, or with null after `timeout` ms.
  function nextEvent(name, timeout, accept = () => true) {
    const bus = PDFViewerApplication.eventBus;
    return new Promise((resolve) => {
      const finish = (event) => {
        clearTimeout(timer);
        bus.off(name, listener);
        resolve(event);
      };
      const listener = (event) => accept(event) && finish(event);
      const timer = setTimeout(() => finish(null), timeout);
      bus.on(name, listener);
    });
  }

  // Runs the viewer's own search for `phrase`, highlighting every match and
  // scrolling to the first; resolves with whether there was one.
  async function find(phrase) {
    const answer = nextEvent("updatefindcontrolstate", 3000, (event) => event.state !== PENDING && event.rawQuery === phrase);
    PDFViewerApplication.eventBus.dispatch("find", {
      source: window, type: "", query: phrase, caseSensitive: false, entireWord: false,
      highlightAll: true, findPrevious: false, matchDiacritics: false,
    });
    const event = await answer;
    return Boolean(event) && event.state !== NOT_FOUND;
  }

  // Highlights the first of `phrases` that the PDF contains (they run from
  // the whole field down to a few words of it, since the PDF doesn't always
  // print a field's text exactly as typed), or clears the highlight if none
  // is there. Resolves with the phrase used, or null.
  window.resumeWorkshopHighlight = async (phrases) => {
    const request = ++latest;
    if (!PDFViewerApplication.pdfDocument) return null;
    for (const phrase of phrases) {
      if (request !== latest) return null;
      if (await find(phrase)) return phrase;
    }
    if (request === latest) PDFViewerApplication.eventBus.dispatch("findbarclose", { source: window });
    return null;
  };

  // Opens the PDF at `url` in place of the current one, at the same scroll
  // position, then highlights as above.
  window.resumeWorkshopOpen = async (url, phrases) => {
    await PDFViewerApplication.initializedPromise; // it may be asked the moment the page has loaded
    const container = PDFViewerApplication.pdfViewer.container;
    const top = container.scrollTop, left = container.scrollLeft;
    const loaded = nextEvent("pagesloaded", 10000);
    await PDFViewerApplication.open({ url });
    await loaded;
    // After the viewer has applied its own initial position.
    await new Promise((resolve) => setTimeout(resolve, 50));
    container.scrollTop = top;
    container.scrollLeft = left;
    return window.resumeWorkshopHighlight(phrases);
  };
})();
