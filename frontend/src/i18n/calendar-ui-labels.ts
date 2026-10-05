import type { Locale } from "@/i18n/types";
import { normalizeAppLocale } from "@/i18n/types";

/** Etiquetas del calendario de reuniones (automatización) — mapa fijo por idioma. */
export type CalendarUiLabels = {
  filterAll: string;
  filterOutlook: string;
  filterGoogle: string;
  refresh: string;
  loading: string;
  meetingsHeading: string;
  pastBadge: string;
  location: string;
  allDay: string;
  viewDay: string;
  viewWeek: string;
  viewMonth: string;
  today: string;
  previous: string;
  next: string;
  viewSelectorLabel: string;
  navLabel: string;
  /** Lleva `{tz}`. */
  timezoneLabel: string;
  filterGroupLabel: string;
  providerGoogle: string;
  providerOutlook: string;
  emptyPeriod: string;
  /** Lleva `{provider}`. */
  providerDisconnected: string;
  /** Lleva `{provider}`. */
  providerError: string;
  retry: string;
  /** Lleva `{provider}`. */
  incompleteLimit: string;
  /** Lleva `{provider}`. */
  incompleteTimeout: string;
  /** Lleva `{provider}`. */
  incompleteError: string;
  /** Lleva `{n}`. */
  discarded: string;
  noEventId: string;
  detailsTitle: string;
  close: string;
  when: string;
  calendarName: string;
  participants: string;
  description: string;
  calendarRegion: string;
  rulesToggleSummary: string;
};

const EN: CalendarUiLabels = {
  filterAll: "All",
  filterOutlook: "Outlook",
  filterGoogle: "Google Calendar",
  refresh: "Refresh",
  loading: "Loading meetings…",
  meetingsHeading: "Upcoming meetings",
  pastBadge: "Past",
  location: "Location",
  allDay: "All day",
  viewDay: "Day",
  viewWeek: "Week",
  viewMonth: "Month",
  today: "Today",
  previous: "Previous",
  next: "Next",
  viewSelectorLabel: "Calendar view",
  navLabel: "Calendar navigation",
  timezoneLabel: "Time zone: {tz}",
  filterGroupLabel: "Filter by calendar",
  providerGoogle: "Google",
  providerOutlook: "Outlook",
  emptyPeriod: "No meetings in this period.",
  providerDisconnected: "{provider} is not connected.",
  providerError: "Could not load {provider} meetings.",
  retry: "Retry",
  incompleteLimit:
    "{provider} has more meetings than can be shown at once. Switch to a shorter view (day or week).",
  incompleteTimeout:
    "{provider} took too long: the list may be incomplete. Retry or switch to a shorter view.",
  incompleteError: "{provider} failed during loading: the list may be incomplete. Retry.",
  discarded: "{n} entries without a valid date are not shown.",
  noEventId: "This event has no identifier, so a dossier cannot be generated for it.",
  detailsTitle: "Meeting details",
  close: "Close",
  when: "When",
  calendarName: "Calendar",
  participants: "Participants",
  description: "Description",
  calendarRegion: "Meetings calendar",
  rulesToggleSummary: "Automation rules",
};

const LABELS: Record<Locale, CalendarUiLabels> = {
  en: EN,
  "en-gb": { ...EN },
  es: {
    filterAll: "Todas",
    filterOutlook: "Outlook",
    filterGoogle: "Google Calendar",
    refresh: "Actualizar",
    loading: "Cargando reuniones…",
    meetingsHeading: "Próximas reuniones",
    pastBadge: "Pasada",
    location: "Ubicación",
    allDay: "Todo el día",
    viewDay: "Día",
    viewWeek: "Semana",
    viewMonth: "Mes",
    today: "Hoy",
    previous: "Anterior",
    next: "Siguiente",
    viewSelectorLabel: "Vista del calendario",
    navLabel: "Navegación del calendario",
    timezoneLabel: "Zona horaria: {tz}",
    filterGroupLabel: "Filtrar por calendario",
    providerGoogle: "Google",
    providerOutlook: "Outlook",
    emptyPeriod: "No hay reuniones en este período.",
    providerDisconnected: "{provider} no está conectado.",
    providerError: "No se pudieron cargar las reuniones de {provider}.",
    retry: "Reintentar",
    incompleteLimit:
      "{provider} tiene más reuniones de las que se pueden mostrar de una vez. Cambia a una vista más corta (día o semana).",
    incompleteTimeout:
      "{provider} tardó demasiado: la lista puede estar incompleta. Reintenta o cambia a una vista más corta.",
    incompleteError: "{provider} falló durante la carga: la lista puede estar incompleta. Reintenta.",
    discarded: "{n} registros sin fecha válida no se muestran.",
    noEventId: "Este evento no tiene identificador, por lo que no se puede generar su dossier.",
    detailsTitle: "Detalle de la reunión",
    close: "Cerrar",
    when: "Cuándo",
    calendarName: "Calendario",
    participants: "Participantes",
    description: "Descripción",
    calendarRegion: "Calendario de reuniones",
    rulesToggleSummary: "Reglas de automatización",
  },
  de: {
    filterAll: "Alle",
    filterOutlook: "Outlook",
    filterGoogle: "Google Kalender",
    refresh: "Aktualisieren",
    loading: "Meetings werden geladen…",
    meetingsHeading: "Anstehende Meetings",
    pastBadge: "Vergangen",
    location: "Ort",
    allDay: "Ganztägig",
    viewDay: "Tag",
    viewWeek: "Woche",
    viewMonth: "Monat",
    today: "Heute",
    previous: "Zurück",
    next: "Weiter",
    viewSelectorLabel: "Kalenderansicht",
    navLabel: "Kalendernavigation",
    timezoneLabel: "Zeitzone: {tz}",
    filterGroupLabel: "Nach Kalender filtern",
    providerGoogle: "Google",
    providerOutlook: "Outlook",
    emptyPeriod: "Keine Meetings in diesem Zeitraum.",
    providerDisconnected: "{provider} ist nicht verbunden.",
    providerError: "Die Meetings von {provider} konnten nicht geladen werden.",
    retry: "Erneut versuchen",
    incompleteLimit:
      "{provider} hat mehr Meetings, als auf einmal angezeigt werden können. Wechsle zu einer kürzeren Ansicht (Tag oder Woche).",
    incompleteTimeout:
      "{provider} hat zu lange gebraucht: Die Liste ist möglicherweise unvollständig. Erneut versuchen oder zu einer kürzeren Ansicht wechseln.",
    incompleteError:
      "{provider} ist beim Laden ausgefallen: Die Liste ist möglicherweise unvollständig. Erneut versuchen.",
    discarded: "{n} Einträge ohne gültiges Datum werden nicht angezeigt.",
    noEventId: "Dieser Termin hat keine Kennung, daher kann kein Dossier erstellt werden.",
    detailsTitle: "Meeting-Details",
    close: "Schließen",
    when: "Wann",
    calendarName: "Kalender",
    participants: "Teilnehmer",
    description: "Beschreibung",
    calendarRegion: "Meeting-Kalender",
    rulesToggleSummary: "Automatisierungsregeln",
  },
  fr: {
    filterAll: "Toutes",
    filterOutlook: "Outlook",
    filterGoogle: "Google Calendar",
    refresh: "Actualiser",
    loading: "Chargement des réunions…",
    meetingsHeading: "Réunions à venir",
    pastBadge: "Passée",
    location: "Lieu",
    allDay: "Toute la journée",
    viewDay: "Jour",
    viewWeek: "Semaine",
    viewMonth: "Mois",
    today: "Aujourd’hui",
    previous: "Précédent",
    next: "Suivant",
    viewSelectorLabel: "Vue du calendrier",
    navLabel: "Navigation du calendrier",
    timezoneLabel: "Fuseau horaire : {tz}",
    filterGroupLabel: "Filtrer par calendrier",
    providerGoogle: "Google",
    providerOutlook: "Outlook",
    emptyPeriod: "Aucune réunion sur cette période.",
    providerDisconnected: "{provider} n’est pas connecté.",
    providerError: "Impossible de charger les réunions de {provider}.",
    retry: "Réessayer",
    incompleteLimit:
      "{provider} compte plus de réunions qu’on ne peut en afficher d’un coup. Passez à une vue plus courte (jour ou semaine).",
    incompleteTimeout:
      "{provider} a mis trop de temps : la liste peut être incomplète. Réessayez ou passez à une vue plus courte.",
    incompleteError:
      "{provider} a échoué pendant le chargement : la liste peut être incomplète. Réessayez.",
    discarded: "{n} entrées sans date valide ne sont pas affichées.",
    noEventId: "Cet événement n’a pas d’identifiant : impossible de générer son dossier.",
    detailsTitle: "Détail de la réunion",
    close: "Fermer",
    when: "Quand",
    calendarName: "Calendrier",
    participants: "Participants",
    description: "Description",
    calendarRegion: "Calendrier des réunions",
    rulesToggleSummary: "Règles d’automatisation",
  },
  it: {
    filterAll: "Tutte",
    filterOutlook: "Outlook",
    filterGoogle: "Google Calendar",
    refresh: "Aggiorna",
    loading: "Caricamento riunioni…",
    meetingsHeading: "Riunioni imminenti",
    pastBadge: "Passata",
    location: "Luogo",
    allDay: "Tutto il giorno",
    viewDay: "Giorno",
    viewWeek: "Settimana",
    viewMonth: "Mese",
    today: "Oggi",
    previous: "Precedente",
    next: "Successivo",
    viewSelectorLabel: "Vista del calendario",
    navLabel: "Navigazione del calendario",
    timezoneLabel: "Fuso orario: {tz}",
    filterGroupLabel: "Filtra per calendario",
    providerGoogle: "Google",
    providerOutlook: "Outlook",
    emptyPeriod: "Nessuna riunione in questo periodo.",
    providerDisconnected: "{provider} non è collegato.",
    providerError: "Impossibile caricare le riunioni di {provider}.",
    retry: "Riprova",
    incompleteLimit:
      "{provider} ha più riunioni di quante se ne possano mostrare insieme. Passa a una vista più breve (giorno o settimana).",
    incompleteTimeout:
      "{provider} ha impiegato troppo: l’elenco potrebbe essere incompleto. Riprova o passa a una vista più breve.",
    incompleteError:
      "{provider} ha avuto un errore durante il caricamento: l’elenco potrebbe essere incompleto. Riprova.",
    discarded: "{n} voci senza una data valida non vengono mostrate.",
    noEventId: "Questo evento non ha un identificativo: non è possibile generarne il dossier.",
    detailsTitle: "Dettagli della riunione",
    close: "Chiudi",
    when: "Quando",
    calendarName: "Calendario",
    participants: "Partecipanti",
    description: "Descrizione",
    calendarRegion: "Calendario delle riunioni",
    rulesToggleSummary: "Regole di automazione",
  },
  pt: {
    filterAll: "Todas",
    filterOutlook: "Outlook",
    filterGoogle: "Google Calendar",
    refresh: "Atualizar",
    loading: "A carregar reuniões…",
    meetingsHeading: "Reuniões próximas",
    pastBadge: "Passada",
    location: "Local",
    allDay: "Dia inteiro",
    viewDay: "Dia",
    viewWeek: "Semana",
    viewMonth: "Mês",
    today: "Hoje",
    previous: "Anterior",
    next: "Seguinte",
    viewSelectorLabel: "Vista do calendário",
    navLabel: "Navegação do calendário",
    timezoneLabel: "Fuso horário: {tz}",
    filterGroupLabel: "Filtrar por calendário",
    providerGoogle: "Google",
    providerOutlook: "Outlook",
    emptyPeriod: "Não há reuniões neste período.",
    providerDisconnected: "{provider} não está ligado.",
    providerError: "Não foi possível carregar as reuniões de {provider}.",
    retry: "Tentar novamente",
    incompleteLimit:
      "{provider} tem mais reuniões do que as que podem ser mostradas de uma vez. Mude para uma vista mais curta (dia ou semana).",
    incompleteTimeout:
      "{provider} demorou demasiado: a lista pode estar incompleta. Tente novamente ou mude para uma vista mais curta.",
    incompleteError:
      "{provider} falhou durante o carregamento: a lista pode estar incompleta. Tente novamente.",
    discarded: "{n} registos sem data válida não são mostrados.",
    noEventId: "Este evento não tem identificador, por isso não é possível gerar o seu dossier.",
    detailsTitle: "Detalhe da reunião",
    close: "Fechar",
    when: "Quando",
    calendarName: "Calendário",
    participants: "Participantes",
    description: "Descrição",
    calendarRegion: "Calendário de reuniões",
    rulesToggleSummary: "Regras de automatização",
  },
};

export function calendarUiLabels(locale: string | Locale): CalendarUiLabels {
  return LABELS[normalizeAppLocale(locale)] ?? LABELS.en;
}

/** Sustituye marcadores `{nombre}`; los que no se pasan quedan intactos. */
export function fillLabel(template: string, vars: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (m, k: string) => (k in vars ? String(vars[k]) : m));
}
