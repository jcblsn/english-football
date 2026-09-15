const state = {
  current: null, document: null, record: null, view: "table", team: null, event: null, meta: "",
  hindcasts: null, series: {}, hindcastSeason: null, hindcastMeasure: null, request: null,
};
const panel = document.getElementById("panel");
const VIEWS = [
  ["table", "Table"],
  ["positions", "Positions"],
  ["teams", "Distributions"],
  ["fixtures", "Fixtures"],
  ["impact", "Impact"],
  ["record", "Record"],
  ["hindcasts", "Hindcasts"],
];
const HINDCAST_MEASURES = [
  ["mean_points", "Expected points"],
  ["mean_position", "Expected position"],
  ["current_points", "Points so far"],
];
const SVG = "http://www.w3.org/2000/svg";
const EVENT_ORDER = [
  "title_probability",
  "top_four_probability",
  "top_five_probability",
  "automatic_promotion_probability",
  "playoff_qualification_probability",
  "playoff_promotion_probability",
  "promotion_probability",
  "relegation_probability",
];

// A club's page lists another club's match when the result moves it at least this much.
// The published data holds every measured row; this cutoff only shortens the list.
const DISPLAY_FLOOR = 0.005;

const pct = (p) => (p === null || p === undefined ? "" : (100 * p).toFixed(1));
const label = (key) => key.replace(/_probability$/, "").replace(/_/g, " ");
const shade = (p, peak) => `rgba(68, 119, 204, ${Math.min(1, Math.sqrt(p / peak)).toFixed(3)})`;
const seasonName = (id) => `${id.slice(0, 4)}/${id.slice(7)}`;
const when = (value) => (value ? new Date(value).toISOString().slice(0, 16).replace("T", " ") : "");

function element(tag, properties = {}, children = []) {
  const { dataset, ...rest } = properties;
  const node = Object.assign(document.createElement(tag), rest);
  Object.assign(node.dataset, dataset ?? {});
  for (const child of [].concat(children)) {
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function table(headers, rows) {
  const head = element("tr", {}, headers.map((h) => element("th", { textContent: h })));
  const body = element("tbody", {}, rows);
  const node = element("table", {}, [element("thead", {}, [head]), body]);
  head.querySelectorAll("th").forEach((th, column) => {
    if (rows.length && [...body.children].every((row) => row.children[column]?.classList.contains("name"))) {
      th.classList.add("name");
    }
    th.onclick = () => {
      const ascending = th.dataset.order !== "asc";
      head.querySelectorAll("th").forEach((other) => delete other.dataset.order);
      th.dataset.order = ascending ? "asc" : "desc";
      const value = (row) => {
        const text = row.children[column].dataset.sort ?? row.children[column].textContent;
        const number = parseFloat(text);
        return Number.isNaN(number) ? text : number;
      };
      [...body.children]
        .sort((a, b) => (value(a) > value(b) ? 1 : value(a) < value(b) ? -1 : 0) * (ascending ? 1 : -1))
        .forEach((row) => body.append(row));
    };
  });
  return node;
}

function cell(text, properties = {}) {
  return element("td", { textContent: text, ...properties });
}

async function load(href) {
  const response = await fetch(href, { cache: "no-store" });
  if (!response.ok) throw new Error(`${href}: ${response.status}`);
  return response.json();
}

async function refresh() {
  const competition = document.getElementById("competition").value;
  const entry =
    state.current.forecasts.find((row) => row.competition_id === competition) ??
    state.current.forecasts[0];
  if (!entry) return;
  state.document = await load(`data/${entry.href}`);
  state.meta =
    `${state.document.model.version} · cutoff ${state.document.model_results_cutoff} · ` +
    `${state.document.simulations.toLocaleString()} paths · generated ${when(state.document.generated_at)}`;
  render();
}

function render() {
  document.querySelectorAll("#views button").forEach((button) => {
    button.setAttribute("aria-current", String(button.dataset.view === state.view));
  });
  panel.replaceChildren();
  document.getElementById("meta").textContent = state.meta;
  if (!["record", "hindcasts"].includes(state.view)) panel.append(...unscheduledNote(), ...unsettledNote());
  const views = { table: tableView, positions: positionsView, teams: teamsView, fixtures: fixturesView, impact: impactView, record: recordView, hindcasts: hindcastView };
  Promise.resolve(views[state.view]()).catch((error) =>
    panel.append(element("p", { className: "error", textContent: error.message }))
  );
}

function unscheduledNote() {
  // Forecasts published before this field existed carry no disclosure.
  const fixtures = state.document.unscheduled_fixtures ?? [];
  if (!fixtures.length) return [];
  const names = Object.fromEntries(state.document.teams.map((team) => [team.team_id, team.name]));
  const listed = fixtures
    .map((f) => `${names[f.home_team_id] ?? f.home_team_id} v ${names[f.away_team_id] ?? f.away_team_id}` +
      (f.match_date ? ` (was ${f.match_date}, simulated on ${f.simulated_on})` : ` (no date, simulated on ${f.simulated_on})`))
    .join("; ");
  return [element("p", { className: "note", textContent: `Postponed or undated: ${listed}. ${state.document.unscheduled_assumption ?? ""}` })];
}

function unsettledNote() {
  // Forecasts published before the in-play policy changed carry no such fixture.
  const fixtures = state.document.unsettled_fixtures ?? [];
  if (!fixtures.length) return [];
  const names = teamNames();
  const listed = fixtures.map((f) => `${names(f.home_team_id)} v ${names(f.away_team_id)}`).join("; ");
  return [element("p", { className: "note", textContent: `Started, no result yet: ${listed}. ${state.document.unsettled_assumption ?? ""}` })];
}

function tableView() {
  const teams = state.document.teams;
  const events = EVENT_ORDER.filter((key) => key in teams[0].events);
  const headers = ["#", "Team", "P", "Pts", "E[pts]", "80% pts", "E[rank]", "80% rank", ...events.map(label)];
  const rows = teams.map((team, position) =>
    element("tr", {}, [
      cell(position + 1),
      element("td", { className: "name" }, [
        element("a", { href: "#", textContent: team.name, onclick: (e) => { e.preventDefault(); state.team = team.team_id; state.view = "teams"; render(); } }),
      ]),
      cell(team.played),
      cell(team.current_points),
      cell(team.mean_points.toFixed(1)),
      cell(team.points_intervals["80"].join("–"), { dataset: { sort: team.points_intervals["80"][0] } }),
      cell(team.mean_position.toFixed(2)),
      cell(team.position_intervals["80"].join("–"), { dataset: { sort: team.position_intervals["80"][0] } }),
      ...events.map((key) => cell(pct(team.events[key]))),
    ])
  );
  panel.append(table(headers, rows));
}

function positionsView() {
  const teams = state.document.teams;
  const places = teams[0].position_probabilities.length;
  const peak = Math.max(...teams.flatMap((team) => team.position_probabilities));
  const headers = ["Team", ...Array.from({ length: places }, (_, i) => String(i + 1))];
  const rows = teams.map((team) =>
    element("tr", {}, [
      element("td", { className: "name", textContent: team.name }),
      ...team.position_probabilities.map((p) =>
        cell(p >= 0.005 ? pct(p) : "", { className: "cell", style: `background:${shade(p, peak)}` })
      ),
    ])
  );
  panel.append(table(headers, rows));
}

function distribution(values, formatter) {
  const peak = Math.max(...values.map(([, p]) => p));
  return element(
    "table",
    {},
    values.map(([key, p]) =>
      element("tr", {}, [
        cell(formatter(key)),
        cell(pct(p)),
        element("td", { className: "name" }, [
          element("span", { className: "bar", style: `width:${Math.round((140 * p) / peak)}px` }),
        ]),
      ])
    )
  );
}

function teamsView() {
  const teams = state.document.teams;
  const chosen = teams.find((team) => team.team_id === state.team) ?? teams[0];
  const chooser = element(
    "select",
    { onchange: (event) => { state.team = event.target.value; render(); } },
    teams.map((team) => element("option", { value: team.team_id, textContent: team.name, selected: team.team_id === chosen.team_id }))
  );
  const points = Object.entries(chosen.points_distribution).map(([k, p]) => [Number(k), p]);
  const positions = chosen.position_probabilities.map((p, i) => [i + 1, p]).filter(([, p]) => p > 0);
  panel.append(
    chooser,
    element("div", { className: "grid" }, [
      element("div", { className: "card" }, [
        element("h2", { textContent: `Final points — mean ${chosen.mean_points.toFixed(1)}, 90% ${chosen.points_intervals["90"].join("–")}` }),
        distribution(points, String),
      ]),
      element("div", { className: "card" }, [
        element("h2", { textContent: `Finishing position — mean ${chosen.mean_position.toFixed(2)}, 90% ${chosen.position_intervals["90"].join("–")}` }),
        distribution(positions, String),
      ]),
      element("div", { className: "card" }, [
        element("h2", { textContent: "Event probabilities" }),
        table(["Event", "%"], Object.entries(chosen.events).map(([key, p]) => element("tr", {}, [element("td", { className: "name", textContent: label(key) }), cell(pct(p))]))),
      ]),
    ]),
    ...weeklyImpact(chosen)
  );
}

function weeklyImpact(chosen) {
  const heading = element("h2", { textContent: "Matches that matter this week" });
  const impact = state.document.impact;
  if (!impact || !impact.fixtures.length) {
    return [heading, element("p", { className: "muted", textContent: "No matches are inside the impact window." })];
  }
  const names = teamNames();
  const slate = impactSlate(impact);
  const mine = (rows) => rows.filter((row) => row.team_id === chosen.team_id);
  // A forecast from before this feature measures only the two clubs of each match.
  const everyClub = (impact.coverage ?? "participants") === "every_team";
  const floorText = `${(100 * (impact.movement_floor ?? 0)).toFixed(3)} percentage points`;
  const listedText = `${(100 * DISPLAY_FLOOR).toFixed(1)} percentage points`;
  const available = EVENT_ORDER.filter((event) =>
    slate.some(({ rows }) => mine(rows).some((row) => row.event === event))
  );
  if (!available.length) {
    return [heading, element("p", { className: "muted", textContent: everyClub
      ? `No match in the window moves ${chosen.name} by more than ${floorText}.`
      : `This forecast measures only the two clubs of each match. ${chosen.name} has no match in the window.` })];
  }
  if (!available.includes(state.event)) {
    state.event = available.reduce(
      (best, event) => (clubPeak(slate, chosen.team_id, event) > clubPeak(slate, chosen.team_id, best) ? event : best),
      available[0]
    );
  }
  const own = [];
  const others = [];
  const quiet = [];
  const missing = [];
  for (const { fixture, rows } of slate) {
    const plays = fixture.home_team_id === chosen.team_id || fixture.away_team_id === chosen.team_id;
    const row = mine(rows).find((row) => row.event === state.event);
    if (row) {
      const entry = [row.rms, impactRow(fixture, row, names, { fixtureOnly: true })];
      // The club's own match always shows; another club's match must clear the cutoff.
      if (plays) own.push(entry);
      else if (row.rms >= DISPLAY_FLOOR) others.push(entry);
      else quiet.push(fixture);
    } else if (fixture.unavailable_reason) {
      missing.push(fixture);
    } else if (plays) {
      own.push([0, impactRow(fixture, null, names, { fixtureOnly: true })]);
    } else {
      quiet.push(fixture);
    }
  }
  others.sort((a, b) => b[0] - a[0]);
  const headers = ["Kickoff (UTC)", "Match", "Now", "If home win", "If draw", "If away win", "RMS", "Swing", ""];
  const nodes = [
    heading,
    element("select", { onchange: (event) => { state.event = event.target.value; render(); } },
      available.map((event) => element("option", { value: event, textContent: label(event), selected: event === state.event }))
    ),
    element("p", { className: "muted", textContent:
      `Each row shows the ${label(state.event)} chance of ${chosen.name} after each result of that match. ` +
      `RMS is the expected movement of that chance. ` +
      (everyClub ? `The list has ${others.length} matches that ${chosen.name} does not play. ` : "") +
      `${impact.basis}` }),
  ];
  if (own.length) {
    nodes.push(
      element("h2", { textContent: `${chosen.name} play` }),
      table(headers, own.map(([, row]) => row))
    );
  }
  nodes.push(
    element("h2", { textContent: "Other matches" }),
    others.length
      ? table(headers, others.map(([, row]) => row))
      : element("p", { className: "muted", textContent: everyClub
          ? `No other match in the window moves this chance by ${listedText} or more.`
          : `This forecast measures only the two clubs of each match. It has no number for ${chosen.name} on the other ${quiet.length} matches of the window.` })
  );
  if (quiet.length && everyClub) {
    nodes.push(element("p", { className: "muted", textContent:
      `${quiet.length} more matches move this chance by less than ${listedText}. They are not listed.` }));
  }
  if (missing.length) {
    nodes.push(element("p", { className: "note", textContent:
      `${missing.length} finished matches have no forecast from before their kickoff: ` +
      `${missing.map((fixture) => `${names(fixture.home_team_id)} v ${names(fixture.away_team_id)}`).join("; ")}. ` +
      `${missing[0].unavailable_reason}` }));
  }
  return nodes;
}

function clubPeak(slate, team, event) {
  return Math.max(0, ...slate.flatMap(({ rows }) =>
    rows.filter((row) => row.team_id === team && row.event === event).map((row) => row.rms)
  ));
}

function fixturesView() {
  const names = Object.fromEntries(state.document.teams.map((team) => [team.team_id, team.name]));
  const rows = state.document.matches.map((match) =>
    element("tr", {}, [
      cell(when(match.kickoff_time)),
      element("td", { className: "name", textContent: names[match.home_team_id] ?? match.home_team_id }),
      element("td", { className: "name", textContent: names[match.away_team_id] ?? match.away_team_id }),
      cell(pct(match.p_home)),
      cell(pct(match.p_draw)),
      cell(pct(match.p_away)),
      cell(match.score_probabilities ? topScores(match.score_probabilities) : "", { className: "muted" }),
    ])
  );
  panel.append(table(["Kickoff (UTC)", "Home", "Away", "H", "D", "A", "Likeliest scores"], rows));
}

function topScores(scores) {
  const cells = [];
  scores.grid_home_rows_away_columns.forEach((row, home) =>
    row.forEach((p, away) => cells.push([`${home}-${away}`, p]))
  );
  return cells
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([score, p]) => `${score} ${pct(p)}%`)
    .join("  ");
}

function teamNames() {
  const names = Object.fromEntries(state.document.teams.map((team) => [team.team_id, team.name]));
  return (id) => names[id] ?? id;
}

function impactSlate(impact) {
  const baselines = Object.fromEntries(state.document.teams.map((team) => [team.team_id, team.events]));
  return impact.fixtures.map((fixture) => ({ fixture, rows: impactRows(fixture, baselines) }));
}

// A forecast published before the all-club impact holds one record for each club and event.
function impactRows(fixture, baselines) {
  const blocks = fixture.impacts ?? {};
  if (Array.isArray(blocks)) {
    return blocks.map((row) => ({
      team_id: row.team_id,
      event: row.event,
      baseline: row.baseline,
      conditional: row.conditional,
      rms: row.rms_movement,
      swing: row.swing,
      sufficient: row.sufficient_sample,
    }));
  }
  const rows = [];
  for (const [event, block] of Object.entries(blocks)) {
    block.team_id.forEach((team, index) => {
      const conditional = { home: block.home[index], draw: block.draw[index], away: block.away[index] };
      const reached = Object.values(conditional).filter((p) => p !== null && p !== undefined);
      rows.push({
        team_id: team,
        event,
        // A finished match keeps the baseline of its own forecast; a coming match uses this one.
        baseline: block.baseline ? block.baseline[index] : baselines[team]?.[event],
        conditional,
        rms: block.rms_movement[index],
        swing: reached.length ? Math.max(...reached) - Math.min(...reached) : 0,
        sufficient: fixture.sufficient_sample !== false,
      });
    });
  }
  return rows;
}

function impactRow(fixture, row, names, { fixtureOnly = false } = {}) {
  const cells = [
    cell(when(fixture.kickoff_time) || fixture.match_date),
    element("td", { className: "name", textContent: `${names(fixture.home_team_id)} v ${names(fixture.away_team_id)}` }),
  ];
  if (!fixtureOnly) {
    cells.push(
      element("td", { className: "name", textContent: names(row.team_id) }),
      cell(fixture.home_team_id === row.team_id ? "H" : fixture.away_team_id === row.team_id ? "A" : "", { className: "muted" })
    );
  }
  cells.push(
    cell(row ? pct(row.baseline) : ""),
    cell(row ? pct(row.conditional.home) : ""),
    cell(row ? pct(row.conditional.draw) : ""),
    cell(row ? pct(row.conditional.away) : ""),
    cell(row ? pct(row.rms) : ""),
    cell(row ? pct(row.swing) : ""),
    cell(impactStatus(fixture, row), { className: "muted" })
  );
  return element("tr", {}, cells);
}

function impactStatus(fixture, row) {
  const marks = [];
  if (fixture.status === "in_progress" || fixture.status === "awaiting_result") marks.push("in play");
  if (fixture.outcome) marks.push(`result ${fixture.outcome}`);
  if (fixture.carried_from) marks.push("before kickoff");
  if (fixture.unavailable_reason) marks.push("no record before kickoff");
  if (row && !row.sufficient) marks.push("thin");
  return marks.join(" · ");
}

function impactView() {
  const impact = state.document.impact;
  if (!impact || !impact.fixtures.length) {
    panel.append(element("p", { className: "muted", textContent: "No matches are inside the impact window." }));
    return;
  }
  const names = teamNames();
  const slate = impactSlate(impact);
  const available = EVENT_ORDER.filter((event) => slate.some(({ rows }) => rows.some((row) => row.event === event)));
  if (!available.includes(state.event)) {
    state.event = available.reduce((best, event) => (eventPeak(slate, event) > eventPeak(slate, best) ? event : best), available[0]);
  }
  const rows = [];
  for (const { fixture, rows: measured } of slate) {
    for (const row of measured.filter((row) => row.event === state.event)) {
      rows.push([row.rms, impactRow(fixture, row, names)]);
    }
  }
  rows.sort((a, b) => b[0] - a[0]);
  const carried = slate.filter(({ fixture }) => fixture.carried_from).length;
  panel.append(
    element("select", { onchange: (event) => { state.event = event.target.value; render(); } },
      available.map((event) => element("option", { value: event, textContent: label(event), selected: event === state.event }))
    ),
    element("p", { className: "muted", textContent:
      `${impact.basis} The window holds ${impact.fixtures.length} matches. It opens at the start of the day in London and closes ${impact.horizon_days} days after the forecast. ` +
      `Each row is one club and one match, ranked by how far the result moves that club's ${label(state.event)} chance. ` +
      ((impact.coverage ?? "participants") === "every_team" ? "" : "This forecast measures only the two clubs of each match. ") +
      `${state.document.simulations.toLocaleString()} season paths; smallest outcome sample ${impact.smallest_outcome_count}. ` +
      (carried ? `${carried} matches have a result. Their numbers come from the last forecast before the kickoff.` : "") }),
    table(
      ["Kickoff (UTC)", "Match", "Club", "", "Now", "If home win", "If draw", "If away win", "RMS", "Swing", ""],
      rows.map(([, row]) => row)
    )
  );
}

function eventPeak(slate, event) {
  return Math.max(0, ...slate.flatMap(({ rows }) => rows.filter((row) => row.event === event).map((row) => row.rms)));
}

function recordView() {
  if (!state.record) {
    panel.append(element("p", { className: "muted", textContent: "No forecast record is published yet." }));
    return;
  }
  const summary = state.record.summary;
  panel.append(
    element("h2", { textContent: `Settled H/D/A forecasts — ${state.record.settled.length} scored, ${state.record.unsettled} awaiting results` }),
    table(
      ["Scope", "Matches", "Log loss", "Brier", "Classwise ECE"],
      Object.entries(summary).map(([scope, row]) =>
        element("tr", {}, [
          element("td", { className: "name", textContent: scope }),
          cell(row.scored),
          cell(row.log_loss.toFixed(5)),
          cell(row.brier.toFixed(5)),
          cell(row.classwise_ece.toFixed(5)),
        ])
      )
    ),
    element("h2", { textContent: "Scored matches" }),
    table(
      ["Kickoff (UTC)", "Match", "Outcome", "H", "D", "A", "Forecast"],
      [...state.record.settled].reverse().map((row) =>
        element("tr", {}, [
          cell(when(row.kickoff_time)),
          element("td", { className: "name", textContent: row.match_id.split(":").slice(2).join(" v ") }),
          cell(row.outcome),
          cell(pct(row.p_home)),
          cell(pct(row.p_draw)),
          cell(pct(row.p_away)),
          cell(row.forecast_id),
        ])
      )
    )
  );
}

function hindcastSeasons() {
  const competition = document.getElementById("competition").value;
  const rows = (state.hindcasts?.seasons ?? []).filter((row) => row.competition_id === competition);
  const versions = [...new Set(rows.map((row) => row.model_version))].sort();
  const version = versions.includes(state.document?.model.version) ? state.document.model.version : versions.at(-1);
  return rows.filter((row) => row.model_version === version);
}

// A hindcast is retrospective. This view never mixes it with the live forecast or the record.
async function hindcastView() {
  const seasons = hindcastSeasons();
  if (!seasons.length) {
    panel.append(element("p", { className: "muted", textContent: "No hindcasts are published for this division." }));
    return;
  }
  const entry = seasons.find((row) => row.season_id === state.hindcastSeason) ?? seasons.at(-1);
  state.hindcastSeason = entry.season_id;
  const request = (state.request = {});
  const series = (state.series[entry.href] ??= await load(`data/${entry.href}`));
  if (state.request !== request || state.view !== "hindcasts") return;
  const team = series.teams.find((row) => row.team_id === state.team) ?? series.teams[0];
  const measures = [
    ...HINDCAST_MEASURES,
    ...EVENT_ORDER.filter((key) => key in team.events).map((key) => [key, `${label(key)} chance`]),
  ];
  if (!measures.some(([key]) => key === state.hindcastMeasure)) state.hindcastMeasure = measures[0][0];
  const [measure, measureName] = measures.find(([key]) => key === state.hindcastMeasure);
  const values = team[measure] ?? team.events[measure];
  const probability = measure.endsWith("_probability");
  const format = probability
    ? (value) => `${pct(value)}%`
    : measure === "mean_position" ? (value) => value.toFixed(2)
    : measure === "current_points" ? String : (value) => value.toFixed(1);
  const monday = (origin) => origin.origin_at.slice(0, 10);
  const chooser = (value, options, choose) =>
    element("select", { onchange: (event) => { choose(event.target.value); render(); } },
      options.map(([key, text]) => element("option", { value: key, textContent: text, selected: key === value })));
  document.getElementById("meta").textContent =
    `${series.model.version} · hindcast · ${series.simulations.toLocaleString()} paths · ${series.origins.length} weekly origins`;
  panel.append(
    element("p", { className: "note", textContent: series.notice }),
    element("div", { className: "controls" }, [
      chooser(entry.season_id, seasons.map((row) => [row.season_id, seasonName(row.season_id)]), (value) => { state.hindcastSeason = value; }),
      chooser(team.team_id, [...series.teams].sort((a, b) => a.name.localeCompare(b.name)).map((row) => [row.team_id, row.name]), (value) => { state.team = value; }),
      chooser(measure, measures, (value) => { state.hindcastMeasure = value; }),
    ]),
    element("h2", { textContent: `${team.name}: ${measureName}, ${series.competition_name} ${seasonName(series.season_id)}` }),
    element("p", { className: "muted", textContent: "One estimate each Monday at 09:00 in London, from before the first match until every result is known." }),
    lineChart(series.origins.map(monday), values, {
      probability,
      invert: measure === "mean_position",
      places: series.teams.length,
      format,
      detail: (index) => `Monday ${monday(series.origins[index])} · ${team.played[index]} played · ${team.current_points[index]} points`,
      name: `${team.name} ${measureName}`,
    }),
    element("details", {}, [
      element("summary", { textContent: "Information rules" }),
      element("ul", {}, series.assumptions.map((text) => element("li", { textContent: text }))),
    ]),
    table(
      ["Monday (London)", "Played", "Points", measureName],
      series.origins.map((origin, index) =>
        element("tr", {}, [
          cell(monday(origin)),
          cell(team.played[index]),
          cell(team.current_points[index]),
          cell(format(values[index]), { dataset: { sort: values[index] } }),
        ])
      )
    )
  );
}

function svgNode(tag, attributes = {}, text = null) {
  const node = document.createElementNS(SVG, tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  if (text !== null) node.textContent = text;
  return node;
}

function lineChart(days, values, { probability, invert, places, format, detail, name }) {
  const width = 760, height = 280, left = 46, right = 64, top = 14, bottom = 30;
  let low = 0, high, ticks;
  if (probability) {
    high = 1;
    ticks = [0, 0.25, 0.5, 0.75, 1];
  } else if (invert) {
    low = 1;
    high = places;
    ticks = [...new Set([1, ...[5, 10, 15, 20].filter((tick) => tick < places), places])];
  } else {
    const step = Math.max(...values) > 60 ? 20 : 10;
    high = Math.max(step, Math.ceil(Math.max(...values) / step) * step);
    ticks = Array.from({ length: high / step + 1 }, (_, index) => index * step);
  }
  const x = (index) => left + (days.length > 1 ? (index * (width - left - right)) / (days.length - 1) : 0);
  const y = (value) => {
    const share = (value - low) / (high - low);
    return invert ? top + share * (height - top - bottom) : height - bottom - share * (height - top - bottom);
  };
  const svg = svgNode("svg", { viewBox: `0 0 ${width} ${height}`, role: "img", tabindex: "0", "aria-label": `${name}, weekly. The table below has every value.` });
  for (const tick of ticks) {
    svg.append(
      svgNode("line", { class: "grid-line", x1: left, x2: width - right, y1: y(tick), y2: y(tick) }),
      svgNode("text", { class: "axis", x: left - 6, y: y(tick) + 4, "text-anchor": "end" }, probability ? `${tick * 100}%` : tick)
    );
  }
  days.forEach((day, index) => {
    if (index && day.slice(0, 7) === days[index - 1].slice(0, 7)) return;
    const month = new Date(`${day}T12:00:00Z`).toLocaleString("en-GB", { month: "short", timeZone: "UTC" });
    svg.append(svgNode("text", { class: "axis", x: x(index), y: height - 10, "text-anchor": "middle" }, month));
  });
  const last = values.length - 1;
  const crosshair = svgNode("line", { class: "crosshair", y1: top, y2: height - bottom, visibility: "hidden" });
  const marker = svgNode("circle", { class: "series-dot", r: 4, visibility: "hidden" });
  svg.append(
    crosshair,
    svgNode("path", { class: "series-line", d: values.map((value, index) => `${index ? "L" : "M"}${x(index).toFixed(1)},${y(value).toFixed(1)}`).join("") }),
    svgNode("circle", { class: "series-dot", r: 4, cx: x(last), cy: y(values[last]) }),
    svgNode("text", { class: "end-label", x: x(last) + 8, y: y(values[last]) + 4 }, format(values[last])),
    marker
  );
  const hit = svgNode("rect", { x: left, y: 0, width: width - left - right, height, fill: "transparent" });
  svg.append(hit);
  const tooltip = element("div", { className: "tooltip", hidden: true });
  const wrapper = element("div", { className: "chart" }, [svg, tooltip]);
  let shown = last;
  const show = (index) => {
    shown = Math.max(0, Math.min(last, index));
    const cx = x(shown), cy = y(values[shown]);
    crosshair.setAttribute("x1", cx);
    crosshair.setAttribute("x2", cx);
    marker.setAttribute("cx", cx);
    marker.setAttribute("cy", cy);
    crosshair.setAttribute("visibility", "visible");
    marker.setAttribute("visibility", "visible");
    tooltip.replaceChildren(element("strong", { textContent: format(values[shown]) }), element("span", { textContent: detail(shown) }));
    tooltip.style.left = `${(100 * cx) / width}%`;
    tooltip.style.top = `${(100 * cy) / height}%`;
    tooltip.hidden = false;
  };
  const hide = () => {
    crosshair.setAttribute("visibility", "hidden");
    marker.setAttribute("visibility", "hidden");
    tooltip.hidden = true;
  };
  hit.onpointermove = (event) => {
    const box = svg.getBoundingClientRect();
    const position = ((event.clientX - box.left) * width) / box.width;
    show(Math.round(((position - left) / (width - left - right)) * last));
  };
  hit.onpointerleave = hide;
  svg.onfocus = () => show(shown);
  svg.onblur = hide;
  svg.onkeydown = (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    show(shown + (event.key === "ArrowRight" ? 1 : -1));
  };
  return wrapper;
}

async function start() {
  try {
    state.current = await load("data/current.json");
  } catch (error) {
    panel.append(element("p", { className: "error", textContent: `No published forecasts found (${error.message}). Run: uv run epl-forecast operate` }));
    return;
  }
  state.record = await load("data/record.json").catch(() => null);
  state.hindcasts = await load("data/hindcasts/index.json").catch(() => null);
  const competitions = document.getElementById("competition");
  competitions.append(
    ...state.current.forecasts.map((row) => element("option", { value: row.competition_id, textContent: row.competition_name }))
  );
  document.getElementById("views").append(
    ...VIEWS.map(([view, text]) =>
      element("button", { textContent: text, dataset: { view }, onclick: () => { state.view = view; render(); } })
    )
  );
  competitions.onchange = refresh;
  await refresh();
}

start();
