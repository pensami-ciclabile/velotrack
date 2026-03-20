/* Traffic light hours highlight — pick value based on day of week */
document.addEventListener("DOMContentLoaded", function () {
    var el = document.querySelector(".tl-highlight");
    if (!el) return;
    var day = new Date().getDay(); // 0=Sun, 6=Sat
    var key = day === 0 ? "sunday" : day === 6 ? "saturday" : "weekday";
    var hours = el.getAttribute("data-" + key);
    if (!hours) return;
    var span = el.querySelector(".tl-hours-value");
    if (span) span.textContent = hours;
    var labels = el.querySelectorAll(".tl-day-label");
    var labelIt = key === "sunday" ? "domenica" : key === "saturday" ? "sabato" : "giorno feriale";
    var labelEn = key === "sunday" ? "Sunday" : key === "saturday" ? "Saturday" : "weekday";
    for (var i = 0; i < labels.length; i++) {
        var parent = labels[i].closest("[class*='i18n-']");
        labels[i].textContent = parent && parent.classList.contains("i18n-en") ? labelEn : labelIt;
    }
});

/* Extra rides — pick value based on day of week */
document.addEventListener("DOMContentLoaded", function () {
    var el = document.querySelector("[data-rides-weekday]");
    if (!el) return;
    var day = new Date().getDay();
    var key = day === 0 ? "sunday" : day === 6 ? "saturday" : "weekday";
    var rides = el.getAttribute("data-rides-" + key);
    if (!rides) return;
    var span = el.querySelector(".tl-rides-value");
    if (span) span.textContent = rides;
});

/* Commute calculator */
document.addEventListener("DOMContentLoaded", function () {
    var dataEl = document.getElementById("commute-data");
    if (!dataEl) return;
    var data = JSON.parse(dataEl.textContent);
    var lineSelect = document.getElementById("commute-line-select");
    var fromSelect = document.getElementById("commute-from-select");
    var toSelect = document.getElementById("commute-to-select");
    var monthValue = document.getElementById("commute-month-value");
    var nodata = document.getElementById("commute-nodata");
    var currentItem = null;

    // Populate line dropdown
    data.forEach(function (item) {
        var opt = document.createElement("option");
        opt.value = item.line;
        opt.textContent = "Linea " + item.line + " / Line " + item.line;
        lineSelect.appendChild(opt);
    });

    function populateStopSelect(sel, stops, placeholder) {
        sel.innerHTML = "";
        var def = document.createElement("option");
        def.value = "";
        def.disabled = true;
        def.selected = true;
        def.textContent = placeholder;
        sel.appendChild(def);
        stops.forEach(function (name, i) {
            var opt = document.createElement("option");
            opt.value = i;
            opt.textContent = name;
            sel.appendChild(opt);
        });
        sel.disabled = false;
    }

    function updateResult() {
        if (!currentItem || currentItem.tl_wait === null) return;
        var fromIdx = parseInt(fromSelect.value, 10);
        var toIdx = parseInt(toSelect.value, 10);
        if (isNaN(fromIdx) || isNaN(toIdx) || fromIdx === toIdx) {
            monthValue.textContent = "\u2014";
            return;
        }
        var totalStops = currentItem.stops.length;
        var fraction = Math.abs(toIdx - fromIdx) / (totalStops - 1);
        var oneWay = currentItem.tl_wait * fraction;
        var monthly = Math.round(oneWay * 2 * 22 / 60);
        monthValue.textContent = monthly;
    }

    lineSelect.addEventListener("change", function () {
        var lineNum = parseInt(lineSelect.value, 10);
        currentItem = data.find(function (d) { return d.line === lineNum; });
        monthValue.textContent = "\u2014";
        nodata.style.display = "none";
        if (!currentItem || currentItem.tl_wait === null) {
            fromSelect.innerHTML = "<option value='' disabled selected>--</option>";
            toSelect.innerHTML = "<option value='' disabled selected>--</option>";
            fromSelect.disabled = true;
            toSelect.disabled = true;
            if (currentItem) nodata.style.display = "block";
            return;
        }
        populateStopSelect(fromSelect, currentItem.stops, "Partenza / From");
        populateStopSelect(toSelect, currentItem.stops, "Arrivo / To");
    });

    fromSelect.addEventListener("change", updateResult);
    toSelect.addEventListener("change", updateResult);
});

/* Comparison chart for the lines page. */
document.addEventListener("DOMContentLoaded", function () {
    var canvas = document.getElementById("comparison-chart");
    if (!canvas) return;

    var lines = JSON.parse(canvas.getAttribute("data-lines"));
    if (!lines || !lines.length) return;

    var labels = lines.map(function (l) { return l.display_name; });
    var avgSpeeds = lines.map(function (l) { return l.stats.speed.avg_moving; });
    var totalDelays = lines.map(function (l) { return l.stats.total_delay; });

    new Chart(canvas, {
        type: "bar",
        data: {
            labels: labels,
            datasets: [
                {
                    label: "Avg Speed (km/h)",
                    data: avgSpeeds,
                    backgroundColor: "rgba(26, 111, 181, 0.7)",
                    yAxisID: "y"
                },
                {
                    label: "Total Delay (s)",
                    data: totalDelays,
                    backgroundColor: "rgba(220, 60, 60, 0.7)",
                    yAxisID: "y1"
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: "top" }
            },
            scales: {
                y: {
                    type: "linear",
                    position: "left",
                    title: { display: true, text: "Avg Speed (km/h)" },
                    beginAtZero: true
                },
                y1: {
                    type: "linear",
                    position: "right",
                    title: { display: true, text: "Total Delay (s)" },
                    beginAtZero: true,
                    grid: { drawOnChartArea: false }
                }
            }
        }
    });
});

/* Home hotspots preview + full hotspots page */
document.addEventListener("DOMContentLoaded", function () {
    function readJsonScript(id) {
        var el = document.getElementById(id);
        if (!el) return null;
        try { return JSON.parse(el.textContent); }
        catch (_e) { return null; }
    }

    function num(v) {
        var n = Number(v);
        return Number.isFinite(n) ? n : 0;
    }

    function esc(v) {
        if (v === null || v === undefined) return "";
        return String(v)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function lineLabel(line) {
        if (!line) return "";
        if (line.label) return line.label;
        var lineNum = line.line_number || line.line_key || "?";
        var destination = line.direction_name || "";
        return destination ? ("Line " + lineNum + " (" + destination + ")") : ("Line " + lineNum);
    }

    function linesSummary(row) {
        if (!row || !Array.isArray(row.lines) || !row.lines.length) return "—";
        return row.lines.map(function (line) {
            var lineNum = line.line_number || line.line_key || "?";
            var destination = (line.direction_name || "").trim();
            return destination ? (lineNum + " (" + destination + ")") : String(lineNum);
        }).join(", ");
    }

    function statForBand(row, band) {
        if (!row) return null;
        if (!band || band === "all") {
            return {
                obs_count: num(row.obs_count),
                mean_wait_s: num(row.mean_wait_s),
                median_wait_s: num(row.median_wait_s),
                p25_s: num(row.p25_s),
                p75_s: num(row.p75_s),
                min_s: num(row.min_s),
                max_s: num(row.max_s)
            };
        }
        if (!row.time_bands || !row.time_bands[band]) return null;
        return row.time_bands[band];
    }

    function timeBandKeys(dataset) {
        var set = new Set();
        dataset.forEach(function (row) {
            if (!row.time_bands) return;
            Object.keys(row.time_bands).forEach(function (k) { set.add(k); });
        });
        var order = { am_peak: 0, midday: 1, pm_peak: 2, evening: 3, night: 4, unknown: 5 };
        return Array.from(set).sort(function (a, b) {
            var oa = Object.prototype.hasOwnProperty.call(order, a) ? order[a] : 99;
            var ob = Object.prototype.hasOwnProperty.call(order, b) ? order[b] : 99;
            if (oa !== ob) return oa - ob;
            return a.localeCompare(b);
        });
    }

    function categoryColor(cat) {
        if (cat === "traffic_light") return "#d64545";
        if (cat === "combined") return "#e2722c";
        if (cat === "tram_stop") return "#3f9f67";
        if (cat === "bottleneck") return "#2d6fae";
        return "#6f6f6f";
    }

    function categoryLabel(cat) {
        if (cat === "traffic_light") return "Traffic light";
        if (cat === "combined") return "Combined";
        if (cat === "tram_stop") return "Tram stop";
        if (cat === "bottleneck") return "Bottleneck";
        return "Unknown";
    }

    function markerRadius(obs) {
        var o = num(obs);
        return Math.max(6, Math.min(18, 6 + Math.sqrt(o) * 2));
    }

    function sortRows(rows, band) {
        return rows.slice().sort(function (a, b) {
            var sa = statForBand(a, band);
            var sb = statForBand(b, band);
            var ma = sa ? num(sa.mean_wait_s) : 0;
            var mb = sb ? num(sb.mean_wait_s) : 0;
            if (mb !== ma) return mb - ma;
            var oa = sa ? num(sa.obs_count) : 0;
            var ob = sb ? num(sb.obs_count) : 0;
            if (ob !== oa) return ob - oa;
            return String(a.location_key || "").localeCompare(String(b.location_key || ""));
        });
    }

    var catIcons = {
        traffic_light: "traffic",
        combined: "layers",
        tram_stop: "tram",
        bottleneck: "alt_route"
    };

    function renderHomeCards(container, rows) {
        if (!container) return;
        if (!rows || !rows.length) {
            container.innerHTML = "<p class='text-secondary'>—</p>";
            return;
        }
        var html = "<div class='space-y-0 divide-y divide-outline-variant/10'>";
        rows.forEach(function (row, idx) {
            var cat = row.category || "unknown";
            var color = categoryColor(cat);
            var icon = catIcons[cat] || "location_on";
            var wait = num(row.mean_wait_s);
            var waitStr = wait >= 60 ? Math.floor(wait / 60) + "m " + Math.round(wait % 60) + "s" : wait.toFixed(0) + "s";
            var lines = linesSummary(row);
            html += "<div class='flex items-center gap-4 py-3'>"
                + "<span class='text-sm font-bold text-secondary/40 w-5 text-right shrink-0'>" + (idx + 1) + "</span>"
                + "<span class='material-symbols-outlined text-base shrink-0' style='color:" + color + "'>" + icon + "</span>"
                + "<div class='flex-1 min-w-0'>"
                + "<div class='flex items-baseline justify-between gap-2'>"
                + "<span class='text-sm font-semibold text-on-surface truncate'>" + esc(categoryLabel(cat)) + "</span>"
                + "<span class='text-sm font-black tracking-tight text-on-surface shrink-0'>" + waitStr + "</span>"
                + "</div>"
                + "<p class='text-xs text-secondary truncate'>" + num(row.obs_count) + " obs · " + num(row.line_count) + " lines · " + esc(lines) + "</p>"
                + "</div>"
                + "</div>";
        });
        html += "</div>";
        container.innerHTML = html;
    }

    // Home preview (pre-ranked slices — top 6, no filter)
    var slices = readJsonScript("hotspot-slices");
    var homeBody = document.getElementById("home-hotspots-body");
    var homeCat = document.getElementById("home-hotspot-category");
    if (slices && homeBody) {
        var rows = slices["all"] || [];
        renderHomeCards(homeBody, rows.slice(0, 6));
    }

    // Full page (map-first hotspots UX)
    var data = readJsonScript("hotspot-data");
    var dataUrlEl = document.getElementById("hotspot-data-url");
    var mapEl = document.getElementById("hotspots-map");
    var listEl = document.getElementById("hotspots-list");
    var catContainer = document.getElementById("hotspot-category");
    var bandContainer = document.getElementById("hotspot-timeband");
    if (!mapEl || !listEl || !catContainer || !bandContainer) return;

    // Category toggle helpers (multi-select)
    function getActiveCategories() {
        var btns = catContainer.querySelectorAll(".hotspot-cat-btn.is-active");
        var cats = [];
        for (var i = 0; i < btns.length; i++) {
            cats.push(btns[i].getAttribute("data-category"));
        }
        return cats;
    }

    // Time band helpers (single-select)
    function getActiveBand() {
        var btn = bandContainer.querySelector(".hotspot-band-btn.is-active");
        return btn ? btn.getAttribute("data-band") : "all";
    }

    var bandMeta = {
        all:      { icon: "schedule",    label: "All" },
        am_peak:  { icon: "light_mode",  label: "AM Peak" },
        midday:   { icon: "wb_sunny",    label: "Midday" },
        pm_peak:  { icon: "wb_twilight", label: "PM Peak" },
        evening:  { icon: "nights_stay", label: "Evening" },
        night:    { icon: "dark_mode",   label: "Night" },
        unknown:  { icon: "help_outline",label: "Other" }
    };

    function initHotspotsPage(dataset) {
        if (!Array.isArray(dataset)) {
            listEl.innerHTML = "<p class='hotspots-empty'>—</p>";
            return;
        }

        // Populate time band buttons dynamically
        timeBandKeys(dataset).forEach(function (band) {
            var meta = bandMeta[band] || { icon: "help_outline", label: band };
            var btn = document.createElement("button");
            btn.type = "button";
            btn.setAttribute("data-band", band);
            btn.className = "hotspot-band-btn flex items-center gap-1.5 py-2.5 px-3.5 rounded-lg text-xs font-bold transition-all cursor-pointer";
            btn.innerHTML = "<span class='material-symbols-outlined text-sm band-icon'>" + esc(meta.icon) + "</span> " + esc(meta.label);
            bandContainer.appendChild(btn);
        });

        // Category toggle click handler (multi-select)
        catContainer.addEventListener("click", function (evt) {
            var btn = evt.target.closest ? evt.target.closest(".hotspot-cat-btn") : null;
            if (!btn) return;
            btn.classList.toggle("is-active");
            // Prevent deselecting all — if none active, re-activate this one
            if (!catContainer.querySelector(".hotspot-cat-btn.is-active")) {
                btn.classList.add("is-active");
            }
            renderAll();
        });

        // Time band toggle click handler (single-select)
        bandContainer.addEventListener("click", function (evt) {
            var btn = evt.target.closest ? evt.target.closest(".hotspot-band-btn") : null;
            if (!btn) return;
            var allBtns = bandContainer.querySelectorAll(".hotspot-band-btn");
            for (var i = 0; i < allBtns.length; i++) {
                allBtns[i].classList.remove("is-active");
            }
            btn.classList.add("is-active");
            renderAll();
        });

        if (typeof L === "undefined") {
            listEl.innerHTML = "<p class='hotspots-empty'>Map library unavailable.</p>";
            return;
        }

        var map = L.map("hotspots-map", {
            zoomControl: true
        }).setView([45.4642, 9.19], 12);

        L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
            maxZoom: 19,
            attribution: "&copy; OpenStreetMap contributors &copy; CARTO"
        }).addTo(map);

        var markersLayer = L.layerGroup().addTo(map);
        var markersByKey = {};
        var selectedKey = null;
        var currentRows = [];
        var activeBand = "all";

        function popupHtml(row) {
            var bandRows = [];
            var bands = timeBandKeys([row]);
            bands.forEach(function (band) {
                var st = row.time_bands ? row.time_bands[band] : null;
                if (!st || !num(st.obs_count)) return;
                bandRows.push(
                    "<li><strong>" + esc(band) + "</strong>: "
                    + num(st.obs_count) + " obs, "
                    + num(st.mean_wait_s).toFixed(1) + "s</li>"
                );
            });

            var lineRows = [];
            (row.lines || []).forEach(function (line) {
                var perBand = [];
                if (line.time_bands) {
                    Object.keys(line.time_bands).sort().forEach(function (band) {
                        var b = line.time_bands[band];
                        if (!b || !num(b.obs_count)) return;
                        perBand.push(esc(band) + ": " + num(b.mean_wait_s).toFixed(1) + "s (" + num(b.obs_count) + ")");
                    });
                }
                var suffix = perBand.length ? ("<br><span class='hotspot-popup-sub'>" + perBand.join(" · ") + "</span>") : "";
                lineRows.push(
                    "<li><strong>" + esc(lineLabel(line)) + "</strong>: "
                    + num(line.obs_count) + " obs, "
                    + num(line.mean_wait_s).toFixed(1) + "s"
                    + suffix + "</li>"
                );
            });

            return ""
                + "<div class='hotspot-popup'>"
                + "<h3>" + esc(row.category || "unknown") + "</h3>"
                + "<p class='hotspot-popup-coord'>" + esc(row.location_key || "") + "</p>"
                + "<p><strong>Obs:</strong> " + num(row.obs_count)
                + " | <strong>Mean:</strong> " + num(row.mean_wait_s).toFixed(1) + "s"
                + " | <strong>Median:</strong> " + num(row.median_wait_s).toFixed(1) + "s"
                + " | <strong>P25–P75:</strong> " + num(row.p25_s).toFixed(1) + "–" + num(row.p75_s).toFixed(1) + "s</p>"
                + "<p><strong>Time bands</strong></p><ul>" + (bandRows.length ? bandRows.join("") : "<li>—</li>") + "</ul>"
                + "<p><strong>Lines</strong></p><ul>" + (lineRows.length ? lineRows.join("") : "<li>—</li>") + "</ul>"
                + "</div>";
        }

        function renderList(rows, band) {
            if (!rows.length) {
                listEl.innerHTML = "<p class='hotspots-empty'>No hotspots for current filters.</p>";
                return;
            }
            var top = rows.slice(0, 20);
            var html = "<div class='hotspots-list-inner'>";
            top.forEach(function (row, idx) {
                var st = statForBand(row, band);
                var itemClasses = "hotspot-item hotspot-item--" + esc(row.category || "unknown");
                if (selectedKey === row.location_key) itemClasses += " is-active";
                html += ""
                    + "<button type='button' class='" + itemClasses + "' data-location-key='" + esc(row.location_key) + "'>"
                    + "<div class='hotspot-item-top'>"
                    + "<span class='hotspot-item-rank'>#" + (idx + 1) + "</span>"
                    + "<span class='hotspot-item-cat'>" + esc(categoryLabel(row.category)) + "</span>"
                    + "<span class='hotspot-item-wait'>" + num(st.mean_wait_s).toFixed(1) + "s</span>"
                    + "</div>"
                    + "<div class='hotspot-item-meta'>Obs " + num(st.obs_count) + " · Median " + num(st.median_wait_s).toFixed(1) + "s · IQR " + num(st.p25_s).toFixed(1) + "–" + num(st.p75_s).toFixed(1) + "s</div>"
                    + "<div class='hotspot-item-lines'>Lines: " + esc(linesSummary(row)) + "</div>"
                    + "</button>";
            });
            html += "</div>";
            listEl.innerHTML = html;
        }

        function applySelection(locationKey, openPopup) {
            selectedKey = locationKey;
            Object.keys(markersByKey).forEach(function (key) {
                var row = markersByKey[key].row;
                var marker = markersByKey[key].marker;
                var activeStats = statForBand(row, activeBand);
                var baseRadius = markerRadius(activeStats ? activeStats.obs_count : row.obs_count);
                marker.setStyle({
                    radius: key === selectedKey ? baseRadius + 3 : baseRadius,
                    color: key === selectedKey ? "#111" : "#ffffff",
                    weight: key === selectedKey ? 3 : 1.5,
                    fillColor: categoryColor(row.category),
                    fillOpacity: key === selectedKey ? 0.95 : 0.8
                });
            });

            var selected = markersByKey[selectedKey];
            if (selected) {
                map.flyTo([selected.row.lat, selected.row.lon], Math.max(map.getZoom(), 15), { duration: 0.6 });
                if (openPopup) selected.marker.openPopup();
            }

            var cards = listEl.querySelectorAll(".hotspot-item");
            for (var i = 0; i < cards.length; i++) {
                var isActive = cards[i].getAttribute("data-location-key") === selectedKey;
                cards[i].classList.toggle("is-active", isActive);
                if (isActive && openPopup) cards[i].scrollIntoView({ block: "nearest" });
            }
        }

        function renderMap(rows, band) {
            markersLayer.clearLayers();
            markersByKey = {};
            rows.forEach(function (row) {
                var rowStats = statForBand(row, band);
                var marker = L.circleMarker([num(row.lat), num(row.lon)], {
                    radius: markerRadius(rowStats ? rowStats.obs_count : row.obs_count),
                    color: "#ffffff",
                    weight: 1.5,
                    fillColor: categoryColor(row.category),
                    fillOpacity: 0.8
                });
                marker.bindPopup(popupHtml(row));
                marker.on("click", function () {
                    applySelection(row.location_key, true);
                });
                marker.addTo(markersLayer);
                markersByKey[row.location_key] = { marker: marker, row: row };
            });

            if (rows.length) {
                var bounds = L.latLngBounds(rows.map(function (r) { return [num(r.lat), num(r.lon)]; }));
                map.fitBounds(bounds, { padding: [20, 20] });
            }
        }

        function filteredRows() {
            var activeCats = getActiveCategories();
            var band = getActiveBand();
            var rows = dataset.filter(function (row) {
                if (activeCats.indexOf(row.category) === -1) return false;
                var st = statForBand(row, band);
                return !!st && num(st.obs_count) > 0;
            });
            return sortRows(rows, band);
        }

        function renderAll() {
            var band = getActiveBand();
            activeBand = band;
            currentRows = filteredRows();
            renderMap(currentRows, band);
            if (!currentRows.length) {
                selectedKey = null;
                renderList(currentRows, band);
                return;
            }

            var hasSelected = selectedKey && currentRows.some(function (row) { return row.location_key === selectedKey; });
            if (!hasSelected) selectedKey = currentRows[0].location_key;
            renderList(currentRows, band);
            applySelection(selectedKey, false);
        }

        listEl.addEventListener("click", function (evt) {
            var target = evt.target;
            if (!target) return;
            var item = target.closest ? target.closest(".hotspot-item") : null;
            if (!item) return;
            var key = item.getAttribute("data-location-key");
            if (!key) return;
            applySelection(key, true);
        });
        renderAll();

        // Back-to-top button for ranking list
        var scrollTopBtn = document.getElementById("hotspots-scroll-top");
        if (scrollTopBtn) {
            listEl.addEventListener("scroll", function () {
                if (listEl.scrollTop > 120) {
                    scrollTopBtn.classList.remove("hidden");
                    scrollTopBtn.classList.add("flex");
                } else {
                    scrollTopBtn.classList.add("hidden");
                    scrollTopBtn.classList.remove("flex");
                }
            });
            scrollTopBtn.addEventListener("click", function () {
                listEl.scrollTo({ top: 0, behavior: "smooth" });
            });
        }
    }

    if (data) {
        initHotspotsPage(data);
        return;
    }

    if (!dataUrlEl) return;
    var dataUrl = dataUrlEl.getAttribute("data-url");
    if (!dataUrl) return;
    fetch(dataUrl)
        .then(function (res) { return res.ok ? res.json() : []; })
        .then(function (rows) { initHotspotsPage(rows); })
        .catch(function () { listEl.innerHTML = "<p class='hotspots-empty'>—</p>"; });
});
