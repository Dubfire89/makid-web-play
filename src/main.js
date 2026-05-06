import './style.css'

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || ''
const LIBRARY_FILE_ID = import.meta.env.VITE_LIBRARY_FILE_ID || ''
const DRIVE_READONLY_SCOPE = 'https://www.googleapis.com/auth/drive.readonly'
const DRIVE_MEDIA_URL_START = 'https://www.googleapis.com/drive/v3/files/'
const EMPTY_FILTER_VALUE = '__empty__'

const AUDIO_MIME_TYPES_BY_EXTENSION = {
  '.mp3': ['audio/mpeg'],
  '.wav': ['audio/wav', 'audio/x-wav'],
  '.wave': ['audio/wav', 'audio/x-wav'],
  '.aif': ['audio/aiff', 'audio/x-aiff'],
  '.aiff': ['audio/aiff', 'audio/x-aiff'],
  '.flac': ['audio/flac'],
  '.m4a': ['audio/mp4', 'audio/x-m4a'],
}

const TEMPO_FILTERS = [
  { value: 'under_100', label: 'Under 100', matches: tempo => tempo < 100 },
  { value: '100_119', label: '100-119', matches: tempo => tempo >= 100 && tempo <= 119 },
  { value: '120_129', label: '120-129', matches: tempo => tempo >= 120 && tempo <= 129 },
  { value: '130_139', label: '130-139', matches: tempo => tempo >= 130 && tempo <= 139 },
  { value: '140_plus', label: '140+', matches: tempo => tempo >= 140 },
]

const TIER_FILTER_ORDER = ['S', 'A', 'B', 'C', 'D', 'F']
const TIER_SORT_ORDER = ['F', 'D', 'C', 'B', 'A', 'S']
const PROGRESS_SORT_ORDER = ['IDEATION', 'IN_PROGRESS', 'NEEDS_REVISION', 'FINAL_TOUCHES', 'COMPLETED']

const MEDIA_ERROR_CODES = {
  aborted: 1,
  network: 2,
  decode: 3,
  unsupported: 4,
}

const app = document.querySelector('#app')

let allRows = []
let groupedProjects = []
let fileByKey = new Map()
let filterOptions = {
  parentFolders: [],
  genres: [],
  tiers: [],
  progress: [],
}

let googleAccessToken = null
let tokenClient = null
let loginError = ''
let libraryStatus = 'signed_out'
let libraryError = ''
let currentFetchController = null
let playbackRequestId = 0

let uiState = {
  searchText: '',
  filters: {
    parentFolders: new Set(),
    genres: new Set(),
    tiers: new Set(),
    progress: new Set(),
    tempos: new Set(),
  },
  sortBy: 'latest',
  sortDirection: 'desc',
  expandedProjectIds: new Set(),
}

let playback = {
  status: 'idle',
  file: null,
  objectUrl: '',
  error: '',
  notice: '',
}

function textValue(value, emptyText = '-') {
  if (value === null || value === undefined || value === '') return emptyText

  if (Array.isArray(value)) {
    const text = value
      .filter(item => item !== null && item !== undefined && item !== '')
      .map(String)
      .join(', ')

    return text || emptyText
  }

  return String(value)
}

function escapeHtml(value, emptyText = '-') {
  return textValue(value, emptyText).replace(/[&<>"']/g, character => {
    if (character === '&') return '&amp;'
    if (character === '<') return '&lt;'
    if (character === '>') return '&gt;'
    if (character === '"') return '&quot;'
    return '&#39;'
  })
}

function asList(value) {
  if (Array.isArray(value)) {
    return value
      .filter(item => item !== null && item !== undefined && item !== '')
      .map(String)
  }

  if (value === null || value === undefined || value === '') return []

  return [String(value)]
}

function optionValue(value) {
  return textValue(value, '') || EMPTY_FILTER_VALUE
}

function makeOption(value, emptyLabel) {
  const storedValue = optionValue(value)

  return {
    value: storedValue,
    label: storedValue === EMPTY_FILTER_VALUE ? emptyLabel : textValue(value, ''),
  }
}

function addOption(optionMap, value, emptyLabel) {
  const option = makeOption(value, emptyLabel)
  optionMap.set(option.value, option.label)
}

function addListOptions(optionMap, values, emptyLabel) {
  const list = asList(values)

  if (!list.length) {
    addOption(optionMap, '', emptyLabel)
    return
  }

  for (const value of list) {
    addOption(optionMap, value, emptyLabel)
  }
}

function optionsFromMap(optionMap) {
  return [...optionMap.entries()]
    .map(([value, label]) => ({ value, label }))
    .sort((a, b) => {
      if (a.value === EMPTY_FILTER_VALUE) return 1
      if (b.value === EMPTY_FILTER_VALUE) return -1
      return compareText(a.label, b.label)
    })
}

function sortOptionsByPreferredOrder(options, preferredOrder) {
  return [...options].sort((a, b) => {
    if (a.value === EMPTY_FILTER_VALUE) return 1
    if (b.value === EMPTY_FILTER_VALUE) return -1

    const aIndex = preferredOrder.indexOf(a.label)
    const bIndex = preferredOrder.indexOf(b.label)
    const aRank = aIndex === -1 ? preferredOrder.length : aIndex
    const bRank = bIndex === -1 ? preferredOrder.length : bIndex

    if (aRank !== bRank) return aRank - bRank
    return compareText(a.label, b.label)
  })
}

function dateToTime(value) {
  if (!value) return 0

  const asNumber = Number(value)
  if (!Number.isNaN(asNumber)) return asNumber

  const asDate = new Date(value)
  if (!Number.isNaN(asDate.getTime())) return asDate.getTime()

  return 0
}

function formatDate(value) {
  const time = dateToTime(value)
  if (!time) return '-'

  return new Date(time).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

function formatTempo(value) {
  const tempo = Number(value)
  if (!Number.isFinite(tempo)) return '-'

  const formattedTempo = Number.isInteger(tempo) ? String(tempo) : tempo.toFixed(1)
  return `${formattedTempo} BPM`
}

function formatBytes(value) {
  const bytes = Number(value)
  if (!Number.isFinite(bytes) || bytes <= 0) return '-'

  const units = ['B', 'KB', 'MB', 'GB']
  let size = bytes
  let unitIndex = 0

  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024
    unitIndex += 1
  }

  const decimals = size >= 10 || unitIndex === 0 ? 0 : 1
  return `${size.toFixed(decimals)} ${units[unitIndex]}`
}

function compareText(a, b) {
  return textValue(a, '').localeCompare(textValue(b, ''), undefined, {
    numeric: true,
    sensitivity: 'base',
  })
}

function compareTextValues(aValue, bValue, direction) {
  const aText = textValue(aValue, '')
  const bText = textValue(bValue, '')

  if (!aText && !bText) return 0
  if (!aText) return 1
  if (!bText) return -1

  const result = compareText(aText, bText)
  return direction === 'asc' ? result : -result
}

function compareNumberValues(aValue, bValue, direction) {
  const aNumber = Number(aValue)
  const bNumber = Number(bValue)
  const aHasNumber = Number.isFinite(aNumber)
  const bHasNumber = Number.isFinite(bNumber)

  if (!aHasNumber && !bHasNumber) return 0
  if (!aHasNumber) return 1
  if (!bHasNumber) return -1

  const result = aNumber - bNumber
  return direction === 'asc' ? result : -result
}

function compareOrderedValues(aValue, bValue, order, direction) {
  const aText = textValue(aValue, '')
  const bText = textValue(bValue, '')

  if (!aText && !bText) return 0
  if (!aText) return 1
  if (!bText) return -1

  const aIndex = order.indexOf(aText)
  const bIndex = order.indexOf(bText)
  const aRank = aIndex === -1 ? order.length : aIndex
  const bRank = bIndex === -1 ? order.length : bIndex
  const result = aRank === bRank ? compareText(aText, bText) : aRank - bRank

  return direction === 'asc' ? result : -result
}

function getFileKey(file) {
  return `${file.project_id}:${file.file_id}:${file.drive_file_id || file.file_name}`
}

function getLatestFile(files) {
  return [...files].sort((a, b) => dateToTime(b.file_created_at) - dateToTime(a.file_created_at))[0] || null
}

function groupByProject(rows) {
  const map = new Map()

  for (const row of rows) {
    const key = row.project_id

    if (!map.has(key)) {
      map.set(key, {
        project_id: row.project_id,
        project_name: row.project_name,
        parent_folder: row.parent_folder,
        genre: row.genre,
        tempo: row.tempo,
        collection: row.collection,
        progress: row.progress,
        tier: row.tier,
        tags: row.tags,
        files: [],
        latestFile: null,
      })
    }

    map.get(key).files.push(row)
  }

  for (const project of map.values()) {
    project.files.sort((a, b) => dateToTime(b.file_created_at) - dateToTime(a.file_created_at))
    project.latestFile = getLatestFile(project.files)
  }

  return [...map.values()].sort((a, b) => compareText(a.project_name, b.project_name))
}

function buildFileLookup(rows) {
  const lookup = new Map()

  for (const row of rows) {
    lookup.set(getFileKey(row), row)
  }

  return lookup
}

function buildFilterOptions(projects) {
  const parentFolders = new Map()
  const genres = new Map()
  const tiers = new Map()
  const progress = new Map()

  for (const project of projects) {
    addOption(parentFolders, project.parent_folder, 'No parent')
    addListOptions(genres, project.genre, 'No genre')
    addOption(tiers, project.tier, 'No tier')
    addOption(progress, project.progress, 'No progress')
  }

  return {
    parentFolders: optionsFromMap(parentFolders),
    genres: optionsFromMap(genres),
    tiers: sortOptionsByPreferredOrder(optionsFromMap(tiers), TIER_FILTER_ORDER),
    progress: sortOptionsByPreferredOrder(optionsFromMap(progress), PROGRESS_SORT_ORDER),
  }
}

function selectedSetMatchesSingle(selectedValues, value) {
  if (!selectedValues.size) return true

  return selectedValues.has(optionValue(value))
}

function selectedSetMatchesList(selectedValues, values) {
  if (!selectedValues.size) return true

  const list = asList(values)

  if (!list.length) {
    return selectedValues.has(EMPTY_FILTER_VALUE)
  }

  return list.some(value => selectedValues.has(optionValue(value)))
}

function projectMatchesSearch(project) {
  const query = uiState.searchText.trim().toLowerCase()
  if (!query) return true

  const searchableValues = [
    project.project_name,
    project.parent_folder,
    project.genre,
    project.collection,
    project.progress,
    project.tier,
    project.tags,
    project.files.map(file => [file.file_name, file.file_ext]),
  ]

  const haystack = searchableValues
    .flat(2)
    .filter(Boolean)
    .join(' ')
    .toLowerCase()

  return haystack.includes(query)
}

function projectMatchesTempo(project) {
  const selectedTempos = uiState.filters.tempos
  if (!selectedTempos.size) return true

  const tempo = Number(project.tempo)
  if (!Number.isFinite(tempo)) return false

  return TEMPO_FILTERS.some(filter => selectedTempos.has(filter.value) && filter.matches(tempo))
}

function projectMatchesFilters(project) {
  return (
    projectMatchesSearch(project) &&
    selectedSetMatchesSingle(uiState.filters.parentFolders, project.parent_folder) &&
    selectedSetMatchesList(uiState.filters.genres, project.genre) &&
    selectedSetMatchesSingle(uiState.filters.tiers, project.tier) &&
    selectedSetMatchesSingle(uiState.filters.progress, project.progress) &&
    projectMatchesTempo(project)
  )
}

function sortProjects(projects) {
  const sortedProjects = [...projects]
  const direction = uiState.sortDirection

  sortedProjects.sort((a, b) => {
    let result = 0

    if (uiState.sortBy === 'name') {
      result = compareTextValues(a.project_name, b.project_name, direction)
    } else if (uiState.sortBy === 'tempo') {
      result = compareNumberValues(a.tempo, b.tempo, direction)
    } else if (uiState.sortBy === 'parent') {
      result = compareTextValues(a.parent_folder, b.parent_folder, direction)
    } else if (uiState.sortBy === 'genre') {
      result = compareTextValues(asList(a.genre)[0], asList(b.genre)[0], direction)
    } else if (uiState.sortBy === 'tier') {
      result = compareOrderedValues(a.tier, b.tier, TIER_SORT_ORDER, direction)
    } else if (uiState.sortBy === 'progress') {
      result = compareOrderedValues(a.progress, b.progress, PROGRESS_SORT_ORDER, direction)
    } else if (uiState.sortBy === 'file_count') {
      result = compareNumberValues(a.files.length, b.files.length, direction)
    } else {
      result = compareNumberValues(
        dateToTime(a.latestFile?.file_created_at),
        dateToTime(b.latestFile?.file_created_at),
        direction
      )
    }

    return result || compareTextValues(a.project_name, b.project_name, 'asc')
  })

  return sortedProjects
}

function getVisibleProjects() {
  return sortProjects(groupedProjects.filter(projectMatchesFilters))
}

function countActiveControls() {
  let count = 0

  if (uiState.searchText.trim()) count += 1

  for (const selectedValues of Object.values(uiState.filters)) {
    count += selectedValues.size
  }

  if (uiState.sortBy !== 'latest') count += 1
  if (uiState.sortDirection !== 'desc') count += 1

  return count
}

function getDefaultSortDirection(sortField) {
  if (sortField === 'latest' || sortField === 'tier') return 'desc'
  return 'asc'
}

function getSortIcon(sortField) {
  if (uiState.sortBy !== sortField) return '&#8597;'
  return uiState.sortDirection === 'asc' ? '&#8593;' : '&#8595;'
}

function getSortButtonLabel(sortField, label) {
  if (uiState.sortBy !== sortField) return `Sort by ${label}`
  return `Sorted by ${label}, ${uiState.sortDirection === 'asc' ? 'ascending' : 'descending'}`
}

function renderSortButton(sortField, label) {
  const active = uiState.sortBy === sortField

  return `
    <span
      class="sortButton ${active ? 'sortButtonActive' : ''}"
      role="button"
      tabindex="0"
      data-sort-field="${escapeHtml(sortField, '')}"
      data-sort-label="${escapeHtml(label, '')}"
      aria-label="${escapeHtml(getSortButtonLabel(sortField, label), '')}"
      title="${escapeHtml(getSortButtonLabel(sortField, label), '')}"
    >
      ${getSortIcon(sortField)}
    </span>
  `
}

function renderCheckboxGroup(groupName, title, sortField, options) {
  const selectedValues = uiState.filters[groupName]

  return `
    <details class="checkboxGroup">
      <summary>
        <span class="filterSummaryText">
          ${escapeHtml(title)}
          <span data-filter-count="${escapeHtml(groupName, '')}">${selectedValues.size ? ` (${selectedValues.size})` : ''}</span>
        </span>
        ${renderSortButton(sortField, title)}
      </summary>
      <div class="checkboxList">
        ${options
          .map(
            option => `
              <label class="checkboxOption">
                <input
                  type="checkbox"
                  data-filter-group="${escapeHtml(groupName, '')}"
                  value="${escapeHtml(option.value, '')}"
                  ${selectedValues.has(option.value) ? 'checked' : ''}
                />
                <span>${escapeHtml(option.label)}</span>
              </label>
            `
          )
          .join('')}
      </div>
    </details>
  `
}

function renderSortOnlyControl(sortField, label) {
  return `
    <div class="sortOnlyGroup">
      <span>${escapeHtml(label)}</span>
      ${renderSortButton(sortField, label)}
    </div>
  `
}

function renderApp() {
  app.innerHTML = `
    <div class="page">
      <header class="topbar">
        <div class="brand">
          <h1>MAKID Web Player</h1>
          <p id="librarySummary"></p>
        </div>

        <div class="topActions">
          <label class="searchLabel" for="searchInput">Search</label>
          <input
            id="searchInput"
            class="search"
            type="search"
            placeholder="Search projects, tags, genre, files..."
            value="${escapeHtml(uiState.searchText, '')}"
          />

          <div id="filterPanel" class="filterPanel">
            ${renderCheckboxGroup('parentFolders', 'Parent', 'parent', filterOptions.parentFolders)}
            ${renderCheckboxGroup('genres', 'Genre', 'genre', filterOptions.genres)}
            ${renderCheckboxGroup('tiers', 'Tier', 'tier', filterOptions.tiers)}
            ${renderCheckboxGroup('progress', 'Progress', 'progress', filterOptions.progress)}
            ${renderCheckboxGroup('tempos', 'BPM', 'tempo', TEMPO_FILTERS)}
            ${renderSortOnlyControl('latest', 'Latest')}
            <button id="resetControlsButton" class="secondaryButton" type="button">Reset</button>
          </div>

          <div class="accountRow">
            <button id="googleButton" class="googleButton" type="button"></button>
            <div id="loginError" class="loginError" hidden></div>
          </div>
        </div>
      </header>

      <main id="projectList" class="projectList"></main>
    </div>

    <section id="playerDock" class="playerDock" aria-live="polite"></section>
  `

  wireControls()
  renderGoogleStatus()
  renderProjectList()
  renderPlayer()
}

function wireControls() {
  const searchInput = document.querySelector('#searchInput')
  const filterPanel = document.querySelector('#filterPanel')
  const resetControlsButton = document.querySelector('#resetControlsButton')
  const googleButton = document.querySelector('#googleButton')
  const projectList = document.querySelector('#projectList')

  searchInput?.addEventListener('input', event => {
    uiState.searchText = event.target.value
    renderProjectList()
  })

  filterPanel?.addEventListener('change', event => {
    const checkbox = event.target.closest('[data-filter-group]')
    if (!checkbox) return

    toggleFilterValue(checkbox.dataset.filterGroup, checkbox.value, checkbox.checked)
    renderProjectList()
  })

  filterPanel?.addEventListener('click', event => {
    const sortButton = event.target.closest('[data-sort-field]')
    if (!sortButton) return

    event.preventDefault()
    event.stopPropagation()
    setSort(sortButton.dataset.sortField)
  })

  filterPanel?.addEventListener('keydown', event => {
    if (event.key !== 'Enter' && event.key !== ' ') return

    const sortButton = event.target.closest('[data-sort-field]')
    if (!sortButton) return

    event.preventDefault()
    setSort(sortButton.dataset.sortField)
  })

  resetControlsButton?.addEventListener('click', resetControls)
  googleButton?.addEventListener('click', signInToGoogle)

  projectList?.addEventListener('click', event => {
    const expandButton = event.target.closest('[data-expand-project-id]')
    if (expandButton) {
      toggleProject(expandButton.dataset.expandProjectId)
      return
    }

    const playButton = event.target.closest('[data-play-file-key]')
    if (!playButton) return

    const file = fileByKey.get(playButton.dataset.playFileKey)
    if (!file) return

    playDriveFile(file)
  })
}

function setSort(sortField) {
  if (uiState.sortBy === sortField) {
    uiState.sortDirection = uiState.sortDirection === 'asc' ? 'desc' : 'asc'
  } else {
    uiState.sortBy = sortField
    uiState.sortDirection = getDefaultSortDirection(sortField)
  }

  updateSortButtons()
  renderProjectList()
}

function toggleFilterValue(groupName, value, checked) {
  const selectedValues = uiState.filters[groupName]
  if (!selectedValues) return

  if (checked) {
    selectedValues.add(value)
  } else {
    selectedValues.delete(value)
  }
}

function resetControls() {
  uiState.searchText = ''
  uiState.sortBy = 'latest'
  uiState.sortDirection = 'desc'

  for (const selectedValues of Object.values(uiState.filters)) {
    selectedValues.clear()
  }

  document.querySelector('#searchInput').value = uiState.searchText

  for (const checkbox of document.querySelectorAll('[data-filter-group]')) {
    checkbox.checked = false
  }

  updateSortButtons()
  renderProjectList()
}

function toggleProject(projectId) {
  if (uiState.expandedProjectIds.has(projectId)) {
    uiState.expandedProjectIds.delete(projectId)
  } else {
    uiState.expandedProjectIds.add(projectId)
  }

  renderProjectList()
}

function renderGoogleStatus() {
  const googleButton = document.querySelector('#googleButton')
  const loginErrorElement = document.querySelector('#loginError')

  if (googleButton) {
    googleButton.disabled = !tokenClient && !googleAccessToken
    googleButton.textContent = googleAccessToken
      ? 'Google Drive connected'
      : tokenClient
        ? 'Connect Google Drive'
        : 'Google login loading...'
    googleButton.classList.toggle('connected', Boolean(googleAccessToken))
  }

  if (loginErrorElement) {
    loginErrorElement.hidden = !loginError
    loginErrorElement.textContent = loginError
  }
}

function renderProjectList() {
  const projectList = document.querySelector('#projectList')
  if (!projectList) return

  if (libraryStatus !== 'ready') {
    updateLibrarySummary(0)
    updateResetButton()
    updateFilterGroupCounts()
    updateSortButtons()
    projectList.innerHTML = `<div class="empty">${escapeHtml(getLibraryStatusMessage())}</div>`
    return
  }

  const visibleProjects = getVisibleProjects()
  updateLibrarySummary(visibleProjects.length)
  updateResetButton()
  updateFilterGroupCounts()
  updateSortButtons()

  if (!visibleProjects.length) {
    projectList.innerHTML = '<div class="empty">No projects found.</div>'
    return
  }

  projectList.innerHTML = visibleProjects.map(renderProject).join('')
}

function updateLibrarySummary(visibleProjectCount) {
  const summary = document.querySelector('#librarySummary')
  if (!summary) return

  if (libraryStatus !== 'ready') {
    summary.textContent = getLibraryStatusMessage()
    return
  }

  const activeControlCount = countActiveControls()
  const shownText =
    visibleProjectCount === groupedProjects.length
      ? `${groupedProjects.length} projects`
      : `${visibleProjectCount} of ${groupedProjects.length} projects`
  const controlText = activeControlCount
    ? ` / ${activeControlCount} active setting${activeControlCount === 1 ? '' : 's'}`
    : ''

  summary.textContent = `${allRows.length} audio files / ${shownText}${controlText}`
}

function getLibraryStatusMessage() {
  if (!googleAccessToken) return 'Connect Google Drive to load your private library'
  if (libraryStatus === 'loading') return 'Loading your private library from Google Drive...'
  if (libraryStatus === 'error') return libraryError || 'Could not load your private library'

  return 'Your private library has not been loaded yet'
}

function updateResetButton() {
  const resetControlsButton = document.querySelector('#resetControlsButton')
  if (!resetControlsButton) return

  resetControlsButton.disabled = countActiveControls() === 0
}

function updateFilterGroupCounts() {
  for (const [groupName, selectedValues] of Object.entries(uiState.filters)) {
    const countElement = document.querySelector(`[data-filter-count="${groupName}"]`)
    if (!countElement) continue

    countElement.textContent = selectedValues.size ? ` (${selectedValues.size})` : ''
  }
}

function updateSortButtons() {
  for (const sortButton of document.querySelectorAll('[data-sort-field]')) {
    const sortField = sortButton.dataset.sortField
    const label = sortButton.dataset.sortLabel
    const active = uiState.sortBy === sortField

    sortButton.classList.toggle('sortButtonActive', active)
    sortButton.innerHTML = getSortIcon(sortField)
    sortButton.setAttribute('aria-label', getSortButtonLabel(sortField, label))
    sortButton.setAttribute('title', getSortButtonLabel(sortField, label))
  }
}

function renderProject(project) {
  const projectId = String(project.project_id)
  const expanded = uiState.expandedProjectIds.has(projectId)
  const latestFile = project.latestFile
  const latestFileKey = latestFile ? getFileKey(latestFile) : ''
  const latestDate = latestFile ? formatDate(latestFile.file_created_at) : '-'
  const projectClasses = ['project']

  if (expanded) projectClasses.push('projectExpanded')

  return `
    <article class="${projectClasses.join(' ')}">
      <div class="projectHeader">
        <div class="projectTitle">
          <h2>${escapeHtml(project.project_name)}</h2>
          <p>${escapeHtml(project.parent_folder)}</p>
          <div class="mobileProjectFacts">
            <span>${escapeHtml(project.tier)}</span>
            <span>${escapeHtml(latestDate)}</span>
          </div>
        </div>

        <div class="projectActions">
          ${
            project.files.length > 1
              ? `<button
                  class="secondaryButton"
                  data-expand-project-id="${escapeHtml(projectId, '')}"
                  aria-expanded="${expanded ? 'true' : 'false'}"
                  aria-controls="project-files-${escapeHtml(projectId, '')}"
                  type="button"
                >
                  <span class="desktopButtonText">${expanded ? 'Hide files' : `Show ${project.files.length} files`}</span>
                  <span class="mobileButtonText">${project.files.length}</span>
                </button>`
              : ''
          }
          <button
            class="primaryButton"
            data-play-file-key="${escapeHtml(latestFileKey, '')}"
            type="button"
            ${latestFile?.drive_file_id ? '' : 'disabled'}
          >
            Play
          </button>
        </div>
      </div>

      <dl class="projectMeta">
        <div>
          <dt>Genre</dt>
          <dd>${escapeHtml(project.genre)}</dd>
        </div>
        <div>
          <dt>BPM</dt>
          <dd>${escapeHtml(formatTempo(project.tempo))}</dd>
        </div>
        <div>
          <dt>Collection</dt>
          <dd>${escapeHtml(project.collection)}</dd>
        </div>
        <div>
          <dt>Progress</dt>
          <dd>${escapeHtml(project.progress)}</dd>
        </div>
        <div>
          <dt>Tier</dt>
          <dd>${escapeHtml(project.tier)}</dd>
        </div>
        <div>
          <dt>Latest</dt>
          <dd>${escapeHtml(latestDate)}</dd>
        </div>
      </dl>

      <div class="projectFooter">
        <span>${project.files.length} file${project.files.length === 1 ? '' : 's'}</span>
        <span>${escapeHtml(project.tags)}</span>
        <span>Latest: ${latestFile ? escapeHtml(latestFile.file_name) : '-'}</span>
      </div>

      ${
        expanded
          ? `<div id="project-files-${escapeHtml(projectId, '')}" class="files">
              ${project.files.map(file => renderFile(file, latestFileKey)).join('')}
            </div>`
          : ''
      }
    </article>
  `
}

function renderFile(file, latestFileKey) {
  const fileKey = getFileKey(file)
  const isActive = playback.file && getFileKey(playback.file) === fileKey
  const isLoading = isActive && playback.status === 'loading'
  const isReady = isActive && playback.status === 'ready'
  const isLatest = latestFileKey === fileKey
  const hasDriveId = Boolean(file.drive_file_id)
  const fileSize = formatBytes(file.drive_size_bytes || file.file_size_bytes)
  const rowClasses = ['file']

  if (isActive) rowClasses.push('fileActive')

  return `
    <div class="${rowClasses.join(' ')}">
      <button
        class="filePlayButton"
        data-play-file-key="${escapeHtml(fileKey, '')}"
        aria-label="Play ${escapeHtml(file.file_name)}"
        type="button"
        ${hasDriveId ? '' : 'disabled'}
      >
        ${isLoading ? 'Loading' : isReady ? 'Loaded' : 'Play'}
      </button>

      <div class="fileInfo">
        <div class="fileName">
          ${escapeHtml(file.file_name)}
          ${isLatest ? '<span class="fileBadge">Latest</span>' : ''}
        </div>
        <div class="fileSub">
          ${escapeHtml(file.file_ext)} / ${escapeHtml(formatDate(file.file_created_at))} / ${escapeHtml(fileSize)} / Drive: ${escapeHtml(file.drive_lookup_status)}
        </div>
      </div>
    </div>
  `
}

function renderPlayer() {
  const playerDock = document.querySelector('#playerDock')
  if (!playerDock) return

  playerDock.innerHTML = getPlayerHtml()

  const audioElement = document.querySelector('#audioPlayer')
  audioElement?.addEventListener('error', () => {
    if (playback.status !== 'ready') return
    setPlaybackError(playback.file, describeAudioElementError(audioElement.error, playback.file))
  })
}

function getPlayerHtml() {
  if (playback.status === 'idle') {
    return `
      <div class="playerDockInner playerIdle">
        <div class="playerText">
          <strong>Player</strong>
          <span>No audio loaded</span>
          <small>Connect Google Drive and play a project or file.</small>
        </div>
      </div>
    `
  }

  const file = playback.file
  const title = file ? escapeHtml(file.file_name) : 'Audio'
  const details = file
    ? `${escapeHtml(file.file_ext)} / ${escapeHtml(formatBytes(file.drive_size_bytes || file.file_size_bytes))}`
    : ''

  if (playback.status === 'loading') {
    return `
      <div class="playerDockInner">
        <div class="playerText">
          <strong>Loading</strong>
          <span>${title}</span>
          <small>${details}</small>
        </div>
        <div class="playerStatus">Downloading from Google Drive...</div>
      </div>
    `
  }

  if (playback.status === 'error') {
    return `
      <div class="playerDockInner playerError">
        <div class="playerText">
          <strong>Playback error</strong>
          <span>${title}</span>
        </div>
        <div class="playerStatus">${escapeHtml(playback.error)}</div>
      </div>
    `
  }

  return `
    <div class="playerDockInner">
      <div class="playerText">
        <strong>Now playing</strong>
        <span>${title}</span>
        <small>${details}</small>
      </div>
      <div class="audioColumn">
        <audio id="audioPlayer" controls src="${escapeHtml(playback.objectUrl, '')}"></audio>
        ${playback.notice ? `<div class="playerNotice">${escapeHtml(playback.notice)}</div>` : ''}
      </div>
    </div>
  `
}

function waitForGoogleIdentityServices() {
  return new Promise((resolve, reject) => {
    if (window.google?.accounts?.oauth2) {
      resolve()
      return
    }

    const startedAt = Date.now()
    const intervalId = window.setInterval(() => {
      if (window.google?.accounts?.oauth2) {
        window.clearInterval(intervalId)
        resolve()
        return
      }

      if (Date.now() - startedAt > 5000) {
        window.clearInterval(intervalId)
        reject(new Error('Google login script did not load. Refresh the page and check your connection.'))
      }
    }, 100)
  })
}

async function initGoogleLogin() {
  if (!GOOGLE_CLIENT_ID) {
    loginError = 'Missing VITE_GOOGLE_CLIENT_ID. Add it to .env.local before connecting Google Drive.'
    renderGoogleStatus()
    return
  }

  try {
    await waitForGoogleIdentityServices()
  } catch (error) {
    loginError = error.message
    renderGoogleStatus()
    return
  }

  tokenClient = window.google.accounts.oauth2.initTokenClient({
    client_id: GOOGLE_CLIENT_ID,
    scope: DRIVE_READONLY_SCOPE,
    callback: tokenResponse => {
      if (tokenResponse.error) {
        console.error(tokenResponse)
        loginError = `Google login failed: ${tokenResponse.error}`
        renderGoogleStatus()
        return
      }

      googleAccessToken = tokenResponse.access_token
      loginError = ''
      renderGoogleStatus()
      loadLibraryFromDrive().catch(error => {
        console.error(error)
        libraryStatus = 'error'
        libraryError = error.message || 'Could not load your private library.'
        renderApp()
      })
    },
  })

  renderGoogleStatus()
}

function signInToGoogle() {
  if (!tokenClient) {
    loginError = 'Google login is not ready yet. Refresh the page once.'
    renderGoogleStatus()
    return
  }

  tokenClient.requestAccessToken()
}

function revokeCurrentObjectUrl() {
  if (!playback.objectUrl) return

  URL.revokeObjectURL(playback.objectUrl)
  playback.objectUrl = ''
}

function stopCurrentFetch() {
  if (!currentFetchController) return

  currentFetchController.abort()
  currentFetchController = null
}

function getMimeTypeCandidates(file) {
  const extension = textValue(file.file_ext, '').toLowerCase()
  const candidates = [
    file.drive_mime_type,
    ...(AUDIO_MIME_TYPES_BY_EXTENSION[extension] || []),
  ].filter(Boolean)

  return [...new Set(candidates)]
}

function choosePlayableMimeType(file) {
  const candidates = getMimeTypeCandidates(file)
  if (!candidates.length) return ''

  const audio = document.createElement('audio')
  const playableType = candidates.find(mimeType => audio.canPlayType(mimeType) !== '')

  return playableType || null
}

function describeUnsupportedAudio(file) {
  const extension = textValue(file.file_ext, '').toUpperCase() || 'this audio type'
  const candidates = getMimeTypeCandidates(file).join(', ') || 'unknown audio type'

  return `This browser cannot play ${extension} files from this app. Reported type: ${candidates}. MP3 and WAV are the safest formats for this first playback version.`
}

function describeAudioElementError(mediaError, file) {
  const name = textValue(file?.file_name)

  if (!mediaError) {
    return `The browser could not play "${name}".`
  }

  if (mediaError.code === MEDIA_ERROR_CODES.aborted) {
    return `Playback was stopped before "${name}" could start.`
  }

  if (mediaError.code === MEDIA_ERROR_CODES.network) {
    return `The browser hit a network error while reading "${name}".`
  }

  if (mediaError.code === MEDIA_ERROR_CODES.decode) {
    return `The browser could not decode "${name}". The file may use an unsupported codec.`
  }

  if (mediaError.code === MEDIA_ERROR_CODES.unsupported) {
    return `The browser does not support the audio format for "${name}".`
  }

  return `The browser could not play "${name}".`
}

async function readDriveErrorMessage(response) {
  const text = await response.text()
  if (!text) return ''

  try {
    const data = JSON.parse(text)
    return data.error?.message || data.error_description || text.slice(0, 240)
  } catch {
    return text.slice(0, 240)
  }
}

function applyLibraryData(data) {
  allRows = data.rows || []
  groupedProjects = groupByProject(allRows)
  fileByKey = buildFileLookup(allRows)
  filterOptions = buildFilterOptions(groupedProjects)
}

async function loadLibraryFromDrive() {
  if (!LIBRARY_FILE_ID) {
    libraryStatus = 'error'
    libraryError = 'Missing VITE_LIBRARY_FILE_ID. Add a private WebAudioFile.json file ID to your env config.'
    renderApp()
    return
  }

  libraryStatus = 'loading'
  libraryError = ''
  renderProjectList()

  const libraryUrl = `${DRIVE_MEDIA_URL_START}${encodeURIComponent(LIBRARY_FILE_ID)}?alt=media`
  const response = await fetch(libraryUrl, {
    headers: {
      Authorization: `Bearer ${googleAccessToken}`,
    },
  })

  if (!response.ok) {
    const details = await readDriveErrorMessage(response)

    if (response.status === 401) {
      googleAccessToken = null
      renderGoogleStatus()
      throw new Error(`Google Drive access expired. Connect Google Drive again.${details ? ` ${details}` : ''}`)
    }

    if (response.status === 403 || response.status === 404) {
      throw new Error(`This Google account cannot read the private library JSON. HTTP ${response.status}.${details ? ` ${details}` : ''}`)
    }

    throw new Error(`Could not load the private library JSON. HTTP ${response.status}.${details ? ` ${details}` : ''}`)
  }

  const data = await response.json()

  applyLibraryData(data)
  libraryStatus = 'ready'
  libraryError = ''
  renderApp()
}

async function fetchDriveAudioBlob(file, signal, playableMimeType) {
  const mediaUrl = `${DRIVE_MEDIA_URL_START}${encodeURIComponent(file.drive_file_id)}?alt=media`
  const response = await fetch(mediaUrl, {
    headers: {
      Authorization: `Bearer ${googleAccessToken}`,
    },
    signal,
  })

  if (!response.ok) {
    const details = await readDriveErrorMessage(response)

    if (response.status === 401) {
      googleAccessToken = null
      throw new Error(`Google Drive access expired. Connect Google Drive again.${details ? ` ${details}` : ''}`)
    }

    throw new Error(`Could not download the file from Google Drive. HTTP ${response.status}.${details ? ` ${details}` : ''}`)
  }

  const downloadedBlob = await response.blob()

  if (!downloadedBlob.size) {
    throw new Error('Google Drive returned an empty audio file.')
  }

  if (playableMimeType && downloadedBlob.type !== playableMimeType) {
    return downloadedBlob.slice(0, downloadedBlob.size, playableMimeType)
  }

  return downloadedBlob
}

function setPlaybackError(file, message) {
  stopCurrentFetch()
  revokeCurrentObjectUrl()

  playback = {
    status: 'error',
    file,
    objectUrl: '',
    error: message,
    notice: '',
  }

  renderPlayer()
  renderProjectList()
}

async function playDriveFile(file) {
  const requestId = playbackRequestId + 1
  playbackRequestId = requestId

  stopCurrentFetch()
  revokeCurrentObjectUrl()

  if (!googleAccessToken) {
    setPlaybackError(file, 'Connect Google Drive before playing files.')
    return
  }

  if (!file.drive_file_id) {
    setPlaybackError(file, 'This row does not have a Google Drive file ID.')
    return
  }

  const playableMimeType = choosePlayableMimeType(file)

  if (playableMimeType === null) {
    setPlaybackError(file, describeUnsupportedAudio(file))
    return
  }

  playback = {
    status: 'loading',
    file,
    objectUrl: '',
    error: '',
    notice: '',
  }
  renderPlayer()
  renderProjectList()

  const fetchController = new AbortController()
  currentFetchController = fetchController

  try {
    const audioBlob = await fetchDriveAudioBlob(file, fetchController.signal, playableMimeType)
    const objectUrl = URL.createObjectURL(audioBlob)

    if (requestId !== playbackRequestId) {
      URL.revokeObjectURL(objectUrl)
      return
    }

    currentFetchController = null
    playback = {
      status: 'ready',
      file,
      objectUrl,
      error: '',
      notice: '',
    }
    renderPlayer()
    renderProjectList()
    startAudioPlayback()
  } catch (error) {
    if (error.name === 'AbortError') return
    if (requestId !== playbackRequestId) return

    console.error(error)
    currentFetchController = null
    renderGoogleStatus()
    setPlaybackError(file, error.message || 'Could not play this file.')
  }
}

function startAudioPlayback() {
  const audioElement = document.querySelector('#audioPlayer')
  if (!audioElement) return

  audioElement.load()

  const playPromise = audioElement.play()

  if (!playPromise?.catch) return

  playPromise.catch(error => {
    if (error.name === 'AbortError') return

    if (error.name === 'NotAllowedError') {
      playback = {
        ...playback,
        notice: 'Audio loaded. Press play in the controls.',
      }
      renderPlayer()
      return
    }

    setPlaybackError(playback.file, `The browser could not start playback. ${error.message || error.name}`)
  })
}

async function boot() {
  renderApp()
  initGoogleLogin()
}

boot().catch(error => {
  console.error(error)
  app.innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`
})
