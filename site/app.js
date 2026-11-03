const dateSelect = document.querySelector("#date-select");
const searchInput = document.querySelector("#search-input");
const scoreSelect = document.querySelector("#score-select");
const statusMessage = document.querySelector("#status");
const jobList = document.querySelector("#job-list");

let jobs = [];

function safeJobUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : "";
  } catch {
    return "";
  }
}

function makeTag(text) {
  const tag = document.createElement("span");
  tag.className = "tag";
  tag.textContent = text;
  return tag;
}

function makeJobCard(job) {
  const card = document.createElement("article");
  card.className = "job-card";

  const heading = document.createElement("div");
  heading.className = "job-heading";
  const title = document.createElement("h2");
  const url = safeJobUrl(job.url);
  if (url) {
    const link = document.createElement("a");
    link.href = url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = job.title || "未命名职位";
    title.append(link);
  } else {
    title.textContent = job.title || "未命名职位";
  }
  heading.append(title);

  const score = document.createElement("span");
  score.className = "score";
  score.textContent = `${Number(job.score) || 0} 分`;
  heading.append(score);
  card.append(heading);

  const meta = document.createElement("p");
  meta.className = "meta";
  meta.textContent = [job.company || "未知公司", job.source, job.posted_at?.slice(0, 10)]
    .filter(Boolean)
    .join(" · ");
  card.append(meta);

  if (job.reason) {
    const reason = document.createElement("p");
    reason.className = "reason";
    reason.textContent = job.reason;
    card.append(reason);
  }

  if (job.description) {
    const description = document.createElement("p");
    description.className = "description";
    description.textContent = job.description;
    card.append(description);
  }

  if (Array.isArray(job.tags) && job.tags.length) {
    const tags = document.createElement("div");
    tags.className = "tags";
    job.tags.slice(0, 8).forEach((tag) => tags.append(makeTag(String(tag))));
    card.append(tags);
  }
  return card;
}

function renderJobs() {
  const query = searchInput.value.trim().toLocaleLowerCase();
  const minimumScore = Number(scoreSelect.value);
  const filtered = jobs.filter((job) => {
    const searchable = [
      job.title, job.company, job.source, job.reason,
      ...(Array.isArray(job.tags) ? job.tags : []),
    ].join(" ").toLocaleLowerCase();
    return Number(job.score) >= minimumScore && searchable.includes(query);
  });

  jobList.replaceChildren(...filtered.map(makeJobCard));
  statusMessage.textContent = filtered.length
    ? `显示 ${filtered.length} 个岗位`
    : jobs.length
      ? "没有符合筛选条件的岗位。"
      : "这一天没有归档到匹配岗位。";
}

async function loadDay(date) {
  statusMessage.textContent = "正在加载岗位记录…";
  jobList.replaceChildren();
  try {
    const response = await fetch(`data/${encodeURIComponent(date)}.json`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const archive = await response.json();
    if (!Array.isArray(archive.jobs)) throw new Error("归档数据格式不正确");
    jobs = archive.jobs;
    renderJobs();
  } catch (error) {
    jobs = [];
    statusMessage.textContent = `加载 ${date} 的记录失败：${error.message}`;
  }
}

async function initialize() {
  try {
    const response = await fetch("data/index.json");
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const archive = await response.json();
    if (!Array.isArray(archive.dates) || !archive.dates.length) {
      dateSelect.replaceChildren(new Option("暂无历史记录", ""));
      dateSelect.disabled = true;
      statusMessage.textContent = "暂无岗位记录；首次 GitHub Actions 运行后会在这里显示。";
      return;
    }

    dateSelect.replaceChildren(
      ...archive.dates.map((date) => new Option(date, date)),
    );
    dateSelect.disabled = false;
    await loadDay(dateSelect.value);
  } catch (error) {
    statusMessage.textContent = `历史记录加载失败：${error.message}`;
  }
}

dateSelect.addEventListener("change", () => loadDay(dateSelect.value));
searchInput.addEventListener("input", renderJobs);
scoreSelect.addEventListener("change", renderJobs);
initialize();
