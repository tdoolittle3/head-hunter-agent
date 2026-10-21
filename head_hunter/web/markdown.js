// Renders the Markdown subset the agents actually produce into DOM nodes.
//
// Built by hand, element by element, on purpose: agent output is untrusted
// model text, so it must never pass through an HTML parser. Nothing here (or
// anywhere in this app) assigns markup from a string. Unknown or malformed
// Markdown degrades to plain text rather than being dropped.
//
// Covered: paragraphs, #..#### headings, **bold**, *italic*/_italic_,
// `code`, ``` fenced blocks, - and 1. lists, > quotes, --- rules,
// pipe tables, and [text](https://...) links (http/https only), plus links
// to a job's own resume download, which the page fetches with the user's token.
(function () {
  "use strict";

  var INLINE = new RegExp(
    "(`+)([^`]+?)\\1" +                        // `code`
    "|\\*\\*([^*]+)\\*\\*" +                   // **bold**
    "|\\*([^*]+)\\*" +                         // *italic*
    "|\\b_([^_]+)_\\b" +                       // _italic_
    "|\\[([^\\]]+)\\]\\((https?:\\/\\/[^\\s)]+" +    // [text](https://url)
    "|\\/api\\/jobs\\/[\\w-]+\\/resume\\.(?:docx|md|pdf))\\)"  // or a resume download
  );

  function inline(parent, text) {
    var rest = text;
    for (;;) {
      var m = INLINE.exec(rest);
      if (!m) {
        if (rest) parent.appendChild(document.createTextNode(rest));
        return;
      }
      if (m.index) parent.appendChild(document.createTextNode(rest.slice(0, m.index)));
      var el;
      if (m[2] !== undefined) {
        el = document.createElement("code");
        el.textContent = m[2];
      } else if (m[3] !== undefined) {
        el = document.createElement("strong");
        inline(el, m[3]);
      } else if (m[4] !== undefined || m[5] !== undefined) {
        el = document.createElement("em");
        inline(el, m[4] !== undefined ? m[4] : m[5]);
      } else {
        el = document.createElement("a");
        if (m[7].charAt(0) === "/") {
          // A download of the user's own file needs their sign-in token, which a
          // plain link cannot carry, so the page performs it (see index.html).
          el.href = "#";
          el.addEventListener("click", function (event) {
            event.preventDefault();
            document.dispatchEvent(new CustomEvent("hh-download", { detail: m[7] }));
          });
        } else {
          el.href = m[7];
          el.target = "_blank";
          el.rel = "noopener noreferrer";
        }
        inline(el, m[6]);
      }
      parent.appendChild(el);
      rest = rest.slice(m.index + m[0].length);
    }
  }

  function paragraph(lines) {
    var p = document.createElement("p");
    for (var i = 0; i < lines.length; i++) {
      if (i) p.appendChild(document.createElement("br"));
      inline(p, lines[i]);
    }
    return p;
  }

  function tableRow(line, cellTag) {
    var row = document.createElement("tr");
    var cells = line.replace(/^\s*\|/, "").replace(/\|\s*$/, "").split("|");
    for (var i = 0; i < cells.length; i++) {
      var cell = document.createElement(cellTag);
      inline(cell, cells[i].trim());
      row.appendChild(cell);
    }
    return row;
  }

  var TABLE_DIVIDER = /^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$/;

  function render(markdown) {
    var out = document.createDocumentFragment();
    var lines = String(markdown).replace(/\r\n/g, "\n").split("\n");
    var i = 0;
    while (i < lines.length) {
      var line = lines[i];

      if (!line.trim()) { i++; continue; }

      var fence = line.match(/^\s*```/);
      if (fence) {
        var code = [];
        i++;
        while (i < lines.length && !/^\s*```/.test(lines[i])) code.push(lines[i++]);
        i++;  // the closing fence, if any
        var pre = document.createElement("pre");
        var codeEl = document.createElement("code");
        codeEl.textContent = code.join("\n");
        pre.appendChild(codeEl);
        out.appendChild(pre);
        continue;
      }

      var heading = line.match(/^(#{1,4})\s+(.*)$/);
      if (heading) {
        var h = document.createElement("h" + heading[1].length);
        inline(h, heading[2].trim());
        out.appendChild(h);
        i++;
        continue;
      }

      if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
        out.appendChild(document.createElement("hr"));
        i++;
        continue;
      }

      if (/^\s*>/.test(line)) {
        var quoted = [];
        while (i < lines.length && /^\s*>/.test(lines[i])) {
          quoted.push(lines[i].replace(/^\s*>\s?/, ""));
          i++;
        }
        var quote = document.createElement("blockquote");
        quote.appendChild(paragraph(quoted));
        out.appendChild(quote);
        continue;
      }

      var bullet = /^\s*[-*]\s+/;
      var numbered = /^\s*\d+[.)]\s+/;
      if (bullet.test(line) || numbered.test(line)) {
        var ordered = numbered.test(line);
        var marker = ordered ? numbered : bullet;
        var list = document.createElement(ordered ? "ol" : "ul");
        while (i < lines.length && marker.test(lines[i])) {
          var item = document.createElement("li");
          inline(item, lines[i].replace(marker, "").trim());
          list.appendChild(item);
          i++;
        }
        out.appendChild(list);
        continue;
      }

      if (line.indexOf("|") >= 0 && i + 1 < lines.length && TABLE_DIVIDER.test(lines[i + 1])) {
        var table = document.createElement("table");
        var thead = document.createElement("thead");
        thead.appendChild(tableRow(line, "th"));
        table.appendChild(thead);
        var tbody = document.createElement("tbody");
        i += 2;  // past the header and its divider
        while (i < lines.length && lines[i].indexOf("|") >= 0 && lines[i].trim()) {
          tbody.appendChild(tableRow(lines[i], "td"));
          i++;
        }
        table.appendChild(tbody);
        out.appendChild(table);
        continue;
      }

      var plain = [];
      while (
        i < lines.length && lines[i].trim() &&
        !/^\s*(```|#{1,4}\s|>|[-*]\s|\d+[.)]\s)/.test(lines[i]) &&
        !(lines[i].indexOf("|") >= 0 && i + 1 < lines.length && TABLE_DIVIDER.test(lines[i + 1]))
      ) {
        plain.push(lines[i]);
        i++;
      }
      out.appendChild(paragraph(plain));
    }
    return out;
  }

  window.HHMarkdown = { render: render };
})();
