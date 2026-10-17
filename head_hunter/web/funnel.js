// Draws the application funnel as a Sankey diagram.
//
// `data` is exactly what GET /api/funnel returns: per-stage counts and, for each
// stage, how many applications ended there. Nothing here counts anything; if the
// numbers on screen are wrong, the bug is in head_hunter/funnel.py.

(function () {
  const NS = "http://www.w3.org/2000/svg";
  const STAGE_COLORS = ["#22d3ee", "#2ee3c6", "#34f0a8", "#b4f05a", "#ffe14d", "#ffc83d"];
  const EXITS = {
    rejected: { label: "Rejected", color: "#ff5636" },
    withdrawn: { label: "Withdrew", color: "#8b7bff" },
    no_response: { label: "No response", color: "#5a6479" },
    in_progress: { label: "In progress", color: "#6aa8ff" },
  };
  const W = 1000, TOP = 96, NODE_W = 14, GAP = 16, MIN_H = 4, LABEL_H = 40, LEFT = 28, RIGHT = 150, BODY_H = 320;

  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  function stageColor(i, n) {
    return STAGE_COLORS[Math.round((i / Math.max(1, n - 1)) * (STAGE_COLORS.length - 1))];
  }

  function stats(data) {
    const s = data.stages, total = data.total;
    const sum = (k) => s.reduce((a, st) => a + (st.exits[k] || 0), 0);
    const waiting = s[0] ? s[0].exits.in_progress || 0 : 0;
    const askedTotal = total - waiting;
    const heard = askedTotal - sum("no_response");
    const pct = (n, d) => (d ? Math.round((n / d) * 100) + "%" : "–");
    const at = (key) => (s.find((x) => x.key === key) || { count: 0 }).count;
    return [
      ["Heard back", pct(heard, askedTotal), heard + " of " + askedTotal + " that have had time to answer"],
      ["Got a screen", pct(at("screen"), total), at("screen") + " of " + total + " applications"],
      ["Reached final", pct(at("final_round"), total), at("final_round") + " final rounds"],
      ["Offers", total ? ((at("offer") / total) * 100).toFixed(1) + "%" : "–", at("offer") + " offers"],
    ];
  }

  function render(svg, data) {
    const stages = data.stages, n = stages.length;
    const step = (W - LEFT - RIGHT) / (n - 1);
    const k = Math.min(14, BODY_H / Math.max(1, data.total));
    const h = (v) => (v > 0 ? Math.max(v * k, MIN_H) : 0);
    const xOf = (i) => LEFT + i * step;

    let defs = "", ribs = "", flows = "", nodes = "", text = "", gid = 0;
    let bottom = TOP + h(stages[0].count);

    function ribbon(xa, ya, ha, xb, yb, hb, ca, cb, tip, flow) {
      const id = "fg" + gid++, mx = (xa + xb) / 2;
      defs += '<linearGradient id="' + id + '" x1="0" x2="1"><stop offset="0" stop-color="' + ca +
        '"/><stop offset="1" stop-color="' + cb + '"/></linearGradient>';
      ribs += '<path class="rib" fill="url(#' + id + ')" d="M' + xa + "," + ya + "C" + mx + "," + ya + " " + mx + "," + yb +
        " " + xb + "," + yb + "L" + xb + "," + (yb + hb) + "C" + mx + "," + (yb + hb) + " " + mx + "," + (ya + ha) +
        " " + xa + "," + (ya + ha) + 'Z"><title>' + esc(tip) + "</title></path>";
      if (flow) {
        const ca2 = ya + ha / 2, cb2 = yb + hb / 2;
        flows += '<path class="flow" d="M' + xa + "," + ca2 + "C" + mx + "," + ca2 + " " + mx + "," + cb2 + " " + xb + "," + cb2 + '"/>';
      }
    }

    stages.forEach((s, i) => {
      const x = xOf(i), color = stageColor(i, n), nh = h(s.count);
      const pct = data.total ? Math.round((s.count / data.total) * 100) : 0;
      nodes += '<rect x="' + x + '" y="' + TOP + '" width="' + NODE_W + '" height="' + Math.max(nh, MIN_H) +
        '" rx="3" fill="' + color + '"/>';
      text += '<text class="hd-l" x="' + x + '" y="30">' + esc(s.label) + "</text>" +
        '<text class="hd-n" x="' + x + '" y="64">' + s.count + "</text>" +
        '<text class="hd-p" x="' + (x + String(s.count).length * 19 + 10) + '" y="64">' + pct + "%</text>";
      if (i === n - 1) return;

      const next = stages[i + 1], xn = xOf(i + 1), nextColor = stageColor(i + 1, n);
      const outs = [["main", next.count]].concat(
        Object.keys(EXITS).map((key) => [key, s.exits[key] || 0])
      ).filter((o) => o[1] > 0);
      const outTotal = outs.reduce((a, o) => a + h(o[1]), 0) || 1;
      const scale = Math.max(nh, MIN_H) / outTotal;
      let off = 0, ly = TOP + h(next.count) + (next.count > 0 ? GAP : 0);

      outs.forEach(([key, v]) => {
        const hs = h(v) * scale, ht = h(v);
        if (key === "main") {
          ribbon(x + NODE_W, TOP + off, hs, xn, TOP, ht, color, nextColor,
            s.label + " to " + next.label + ": " + v + " of " + s.count, true);
        } else {
          const ex = EXITS[key];
          ribbon(x + NODE_W, TOP + off, hs, xn, ly, ht, color, ex.color,
            s.label + ": " + ex.label.toLowerCase() + " " + v, false);
          nodes += '<rect x="' + xn + '" y="' + ly + '" width="' + NODE_W + '" height="' + ht + '" rx="3" fill="' + ex.color + '"/>';
          const ty = ly + ht / 2;
          text += '<text class="ls-l" x="' + (xn + NODE_W + 10) + '" y="' + (ty - 4) + '" fill="' +
            (key === "no_response" ? "#9aa5bb" : ex.color) + '">' + ex.label + "</text>" +
            '<text class="ls-n" x="' + (xn + NODE_W + 10) + '" y="' + (ty + 16) + '">' + v + "</text>";
          bottom = Math.max(bottom, ly + ht);
          ly += Math.max(ht + GAP, LABEL_H);
        }
        off += hs;
      });
    });

    svg.setAttribute("viewBox", "0 0 " + W + " " + Math.ceil(bottom + 36));
    svg.setAttribute("aria-label", "Sankey chart of " + data.total + " applications by stage: " +
      stages.map((s) => s.count + " " + s.label.toLowerCase()).join(", "));
    svg.innerHTML = "<defs>" + defs + '<filter id="glow" x="-100%" y="-20%" width="300%" height="140%">' +
      '<feGaussianBlur stdDeviation="7"/></filter></defs>' +
      '<g class="reveal"><g style="mix-blend-mode:screen">' + ribs + "</g>" + flows + "</g>" +
      '<g class="node"><g filter="url(#glow)" opacity=".75">' + nodes + "</g>" + nodes + "</g>" + text;
  }

  function replay(svg) {
    const r = svg.querySelector(".reveal"), nd = svg.querySelector(".node");
    if (!r || !svg.animate || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    r.animate([{ clipPath: "inset(0 100% 0 0)" }, { clipPath: "inset(0 0 0 0)" }],
      { duration: 1600, easing: "cubic-bezier(.6,.05,.2,1)" });
    nd.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 900, delay: 300, fill: "backwards" });
  }

  window.HHFunnel = { render, replay, stats, NS };
})();
