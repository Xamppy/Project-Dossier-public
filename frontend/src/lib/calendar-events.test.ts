import { describe, expect, it } from "vitest";
import {
  adaptMeetings,
  calendarEventKey,
  descriptionToPlainText,
  initialViewForWidth,
  toFullCalendarEvent,
  windowFromCivilDates,
} from "./calendar-events";

const TZ = "America/Santiago";

function meeting(over: Record<string, unknown> = {}) {
  return {
    id: "ev1",
    tema: "Reunión con Acme",
    descripcion: "Empresa: Acme",
    participantes: "ana@acme.test",
    inicio: "2026-10-05T13:00:00Z",
    fin: "2026-10-05T14:00:00Z",
    ubicacion: "Meet",
    todo_el_dia: false,
    ...over,
  };
}

describe("calendarEventKey", () => {
  it("combina proveedor e id original", () => {
    expect(calendarEventKey("google", "abc")).toBe("google:abc");
    expect(calendarEventKey("microsoft", "abc")).toBe("microsoft:abc");
  });

  it("el mismo id en proveedores distintos no colisiona", () => {
    expect(calendarEventKey("google", "x")).not.toBe(calendarEventKey("microsoft", "x"));
  });
});

describe("adaptMeetings", () => {
  it("mapea tema→title, inicio→start, fin→end y conserva el id original", () => {
    const { events, discarded } = adaptMeetings("google", [meeting()], TZ, "Sin asunto");
    expect(discarded).toBe(0);
    expect(events).toHaveLength(1);
    const e = events[0];
    expect(e.title).toBe("Reunión con Acme");
    expect(e.start).toBe("2026-10-05T13:00:00.000Z");
    expect(e.end).toBe("2026-10-05T14:00:00.000Z");
    expect(e.allDay).toBe(false);
    expect(e.eventId).toBe("ev1");
    expect(e.provider).toBe("google");
    expect(e.key).toBe("google:ev1");
  });

  it("interpreta como UTC un instante sin zona (Outlook legado)", () => {
    const { events } = adaptMeetings("microsoft", [meeting({ inicio: "2026-10-05T13:00:00", fin: "2026-10-05T14:00:00" })], TZ, "x");
    expect(events[0].start).toBe("2026-10-05T13:00:00.000Z");
  });

  it("conserva el offset de origen sin desplazar el instante", () => {
    const { events } = adaptMeetings("google", [meeting({ inicio: "2026-10-05T23:30:00-03:00", fin: "2026-10-06T00:30:00-03:00" })], TZ, "x");
    expect(events[0].start).toBe("2026-10-06T02:30:00.000Z");
    expect(events[0].end).toBe("2026-10-06T03:30:00.000Z");
  });

  it("día completo: usa fechas civiles con fin exclusivo, sin convertir zonas", () => {
    const { events } = adaptMeetings(
      "google",
      [meeting({ inicio: "2026-10-12", fin: "2026-10-13", todo_el_dia: true })],
      TZ,
      "x",
    );
    expect(events[0]).toMatchObject({ allDay: true, start: "2026-10-12", end: "2026-10-13" });
  });

  it("día completo multi-día conserva el fin exclusivo", () => {
    const { events } = adaptMeetings(
      "microsoft",
      [meeting({ inicio: "2026-10-12", fin: "2026-10-15", todo_el_dia: true })],
      TZ,
      "x",
    );
    expect(events[0]).toMatchObject({ start: "2026-10-12", end: "2026-10-15" });
  });

  it("día completo en formato legado (instantes) se resuelve en la zona del usuario", () => {
    // 03:00Z = medianoche del 12 en Santiago (UTC-3 en octubre).
    const { events } = adaptMeetings(
      "microsoft",
      [meeting({ inicio: "2026-10-12T03:00:00Z", fin: "2026-10-13T03:00:00Z", todo_el_dia: true })],
      TZ,
      "x",
    );
    expect(events[0]).toMatchObject({ allDay: true, start: "2026-10-12", end: "2026-10-13" });
  });

  it("día completo sin fin válido omite el fin (FullCalendar lo trata como un día)", () => {
    const { events } = adaptMeetings("google", [meeting({ inicio: "2026-10-12", fin: "", todo_el_dia: true })], TZ, "x");
    expect(events[0].end).toBeNull();
  });

  it("inicio inválido: excluye el evento y lo cuenta como no representable", () => {
    const { events, discarded } = adaptMeetings(
      "google",
      [meeting({ id: "ok" }), meeting({ id: "mal", inicio: "no-es-fecha" }), meeting({ id: "vacio", inicio: "" })],
      TZ,
      "x",
    );
    expect(events.map((e) => e.eventId)).toEqual(["ok"]);
    expect(discarded).toBe(2);
  });

  it("fin ausente, inválido o anterior al inicio: representación puntual sin inventar hora", () => {
    for (const fin of ["", "basura", "2026-10-05T12:00:00Z", "2026-10-05T13:00:00Z"]) {
      const { events } = adaptMeetings("google", [meeting({ fin })], TZ, "x");
      expect(events[0].end).toBeNull();
    }
  });

  it("evento sin id es visible pero sin id de generación", () => {
    const { events } = adaptMeetings("google", [meeting({ id: null }), meeting({ id: "  " })], TZ, "x");
    expect(events).toHaveLength(2);
    expect(events.every((e) => e.eventId === null)).toBe(true);
    expect(new Set(events.map((e) => e.key)).size).toBe(2);
  });

  it("ids repetidos dentro del mismo proveedor reciben claves distintas", () => {
    const { events } = adaptMeetings("google", [meeting(), meeting()], TZ, "x");
    expect(new Set(events.map((e) => e.key)).size).toBe(2);
    expect(events.every((e) => e.eventId === "ev1")).toBe(true);
  });

  it("mismo id en Google y Outlook produce eventos y claves independientes", () => {
    const g = adaptMeetings("google", [meeting()], TZ, "x").events[0];
    const m = adaptMeetings("microsoft", [meeting()], TZ, "x").events[0];
    expect(g.key).not.toBe(m.key);
  });

  it("título vacío usa el texto de reserva", () => {
    const { events } = adaptMeetings("google", [meeting({ tema: "   " })], TZ, "Sin asunto");
    expect(events[0].title).toBe("Sin asunto");
  });

  it("el título HTML se presenta como texto plano", () => {
    const { events } = adaptMeetings("google", [meeting({ tema: "<b>Hola</b> &amp; <i>adiós</i>" })], TZ, "x");
    expect(events[0].title).toBe("Hola & adiós");
  });

  it("campos opcionales ausentes no rompen la adaptación", () => {
    const { events } = adaptMeetings("google", [{ id: "a", inicio: "2026-10-05T13:00:00Z" }], TZ, "Sin asunto");
    expect(events[0]).toMatchObject({ description: "", participants: "", location: "", title: "Sin asunto" });
  });
});

describe("descriptionToPlainText", () => {
  it("convierte HTML en texto plano conservando saltos de línea", () => {
    expect(descriptionToPlainText("<p>Empresa: Acme</p><p>Contacto: Ana<br>Cargo: CEO</p>")).toBe(
      "Empresa: Acme\nContacto: Ana\nCargo: CEO",
    );
  });

  it("elimina scripts, estilos y manejadores sin ejecutarlos ni dejar su contenido", () => {
    const out = descriptionToPlainText(
      '<script>alert(1)</script><style>p{x:y}</style><img src=x onerror="alert(2)">Hola<a href="javascript:alert(3)">enlace</a>',
    );
    expect(out).toBe("Hola enlace");
    expect(out).not.toMatch(/alert|onerror|javascript/);
  });

  it("decodifica entidades en una sola pasada", () => {
    expect(descriptionToPlainText("a &lt;b&gt; &amp;lt; &#65;&#x42; &nbsp;c")).toBe("a <b> &lt; AB c");
  });

  it("vacío o indefinido devuelve cadena vacía", () => {
    expect(descriptionToPlainText(undefined)).toBe("");
    expect(descriptionToPlainText("   ")).toBe("");
  });
});

describe("toFullCalendarEvent", () => {
  it("usa la clave compuesta como id y omite end cuando es null", () => {
    const { events } = adaptMeetings("microsoft", [meeting({ fin: "" })], TZ, "x");
    const fc = toFullCalendarEvent(events[0]);
    expect(fc.id).toBe("microsoft:ev1");
    expect(fc).not.toHaveProperty("end");
    expect(fc.className).toBe("dossier-ev dossier-ev--microsoft"); // v7: `className`, no `classNames`
    expect(fc.extendedProps).toMatchObject({ provider: "microsoft" });
  });
});

describe("windowFromCivilDates", () => {
  it("convierte fechas civiles en instantes con offset de la zona (inicio inclusivo, fin exclusivo)", () => {
    const w = windowFromCivilDates("2026-10-05", "2026-10-12", "America/Santiago");
    expect(w).toEqual({ desde: "2026-10-05T00:00:00-03:00", hasta: "2026-10-12T00:00:00-03:00" });
  });

  it("respeta el cambio de horario dentro del intervalo (Santiago, 6 de septiembre de 2026)", () => {
    const w = windowFromCivilDates("2026-08-31", "2026-10-05", "America/Santiago");
    expect(w.desde).toBe("2026-08-31T00:00:00-04:00");
    expect(w.hasta).toBe("2026-10-05T00:00:00-03:00");
  });

  it("Londres usa +01:00 en verano y +00:00 en invierno", () => {
    expect(windowFromCivilDates("2026-07-01", "2026-07-02", "Europe/London").desde).toBe("2026-07-01T00:00:00+01:00");
    expect(windowFromCivilDates("2026-12-01", "2026-12-02", "Europe/London").desde).toBe("2026-12-01T00:00:00+00:00");
  });

  it("UTC usa +00:00", () => {
    expect(windowFromCivilDates("2026-10-05", "2026-10-06", "UTC")).toEqual({
      desde: "2026-10-05T00:00:00+00:00",
      hasta: "2026-10-06T00:00:00+00:00",
    });
  });

  it("zona inválida recae en UTC en lugar de lanzar", () => {
    expect(windowFromCivilDates("2026-10-05", "2026-10-06", "No/Existe").desde).toBe("2026-10-05T00:00:00+00:00");
  });

  it("acepta fechas con hora y zona (como las entrega FullCalendar) usando solo la parte civil", () => {
    const w = windowFromCivilDates("2026-10-05T00:00:00-03:00", "2026-10-12T00:00:00-03:00", "America/Santiago");
    expect(w.desde).toBe("2026-10-05T00:00:00-03:00");
  });
});

describe("initialViewForWidth (ancho del calendario, no del viewport)", () => {
  it("Día cuando el calendario es estrecho y Semana cuando caben siete columnas legibles", () => {
    expect(initialViewForWidth(0)).toBe("timeGridDay");
    expect(initialViewForWidth(360)).toBe("timeGridDay");
    expect(initialViewForWidth(414)).toBe("timeGridDay"); // tableta de 768 px con el menú lateral
    expect(initialViewForWidth(639)).toBe("timeGridDay");
    expect(initialViewForWidth(640)).toBe("timeGridWeek");
    expect(initialViewForWidth(672)).toBe("timeGridWeek"); // escritorio de 1024 px
    expect(initialViewForWidth(1088)).toBe("timeGridWeek"); // escritorio de 1440 px
  });
});
