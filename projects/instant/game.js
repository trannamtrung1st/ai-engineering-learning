const canvas = document.getElementById("gameCanvas");
const ctx = canvas.getContext("2d");

const playerHpEl = document.getElementById("playerHp");
const enemyHpEl = document.getElementById("enemyHp");
const playerHpBarEl = document.getElementById("playerHpBar");
const enemyHpBarEl = document.getElementById("enemyHpBar");
const shotsCountEl = document.getElementById("shotsCount");
const hitsCountEl = document.getElementById("hitsCount");
const cooldownTextEl = document.getElementById("cooldownText");
const statusEl = document.getElementById("statusText");
const overlay = document.getElementById("overlay");

const MAP = [
  "111111111111",
  "100000000001",
  "101110111101",
  "100010000001",
  "101011011101",
  "100000010001",
  "111010010101",
  "100010000001",
  "101111011101",
  "100000000001",
  "100011100001",
  "111111111111",
];

const TILE = 1;
const FOV = Math.PI / 3;
const HALF_FOV = FOV / 2;
const MAX_DEPTH = 16;
const MOVE_SPEED = 2.5;
const TURN_SPEED = 2.2;
const MOUSE_SENSITIVITY = 0.0028;
const MOUSE_PITCH_SENSITIVITY = 0.0024;
const MAX_PITCH = 0.6;
const BULLET_SPEED = 8.5;
const BULLET_LIFE = 1.8;
const PLAYER_DAMAGE = 34;
const ENEMY_DAMAGE = 10;
const PLAYER_EYE_HEIGHT = 0.55;
const PLAYER_HEIGHT = 1.7;
const ENEMY_BASE_Z = 0;
const ENEMY_HEIGHT = 1.65;
const ENEMY_STUCK_RECOVER_SEC = 0.45;
const ENEMY_REPATH_INTERVAL_SEC = 0.45;

const state = {
  keys: {},
  messageTimer: 0,
  gameOver: false,
  win: false,
  bullets: [],
  stats: {
    shots: 0,
    hits: 0,
  },
  player: {
    x: 1.5,
    y: 1.5,
    angle: 0.2,
    pitch: 0,
    hp: 100,
    shootCooldown: 0,
  },
  enemy: {
    x: 10.2,
    y: 9.2,
    hp: 100,
    alive: true,
    fireCooldown: 0,
    patrolAngle: -Math.PI / 2,
    lastSeenX: 1.5,
    lastSeenY: 1.5,
    roamX: 10.2,
    roamY: 9.2,
    repathTimer: 0,
    stuckTime: 0,
    path: [],
    pathIndex: 0,
    goalCellX: 10,
    goalCellY: 9,
  },
};

function isWall(x, y) {
  if (x < 0 || y < 0 || y >= MAP.length || x >= MAP[0].length) return true;
  return MAP[Math.floor(y)][Math.floor(x)] === "1";
}

function normalizeAngle(a) {
  while (a < -Math.PI) a += Math.PI * 2;
  while (a > Math.PI) a -= Math.PI * 2;
  return a;
}

function setStatus(msg, timeSec = 1.2) {
  statusEl.textContent = msg;
  state.messageTimer = timeSec;
}

function pickEnemyRoamTarget() {
  const width = MAP[0].length;
  const height = MAP.length;
  for (let i = 0; i < 60; i++) {
    const x = 1 + Math.random() * (width - 2);
    const y = 1 + Math.random() * (height - 2);
    if (isWall(x, y)) continue;
    if (Math.hypot(x - state.player.x, y - state.player.y) < 2.2) continue;
    return { x, y };
  }
  return { x: state.enemy.x, y: state.enemy.y };
}

function toCell(v) {
  return Math.floor(v);
}

function toCellCenter(cell) {
  return cell + 0.5;
}

function isWalkableCell(cx, cy) {
  if (cx < 0 || cy < 0 || cy >= MAP.length || cx >= MAP[0].length) return false;
  return MAP[cy][cx] !== "1";
}

function buildPath(startX, startY, goalX, goalY) {
  const sx = toCell(startX);
  const sy = toCell(startY);
  const gx = toCell(goalX);
  const gy = toCell(goalY);
  if (!isWalkableCell(sx, sy) || !isWalkableCell(gx, gy)) return [];

  const key = (x, y) => `${x},${y}`;
  const queue = [{ x: sx, y: sy }];
  const prev = new Map();
  prev.set(key(sx, sy), null);

  const dirs = [
    [1, 0],
    [-1, 0],
    [0, 1],
    [0, -1],
  ];

  while (queue.length > 0) {
    const cur = queue.shift();
    if (cur.x === gx && cur.y === gy) break;
    for (const [dx, dy] of dirs) {
      const nx = cur.x + dx;
      const ny = cur.y + dy;
      const k = key(nx, ny);
      if (!isWalkableCell(nx, ny) || prev.has(k)) continue;
      prev.set(k, cur);
      queue.push({ x: nx, y: ny });
    }
  }

  if (!prev.has(key(gx, gy))) return [];

  const pathCells = [];
  let cur = { x: gx, y: gy };
  while (cur) {
    pathCells.push(cur);
    cur = prev.get(key(cur.x, cur.y));
  }
  pathCells.reverse();

  // Convert to world points.
  return pathCells.map((c) => ({ x: toCellCenter(c.x), y: toCellCenter(c.y) }));
}

function resetGame() {
  state.player.x = 1.5;
  state.player.y = 1.5;
  state.player.angle = 0.2;
  state.player.pitch = 0;
  state.player.hp = 100;
  state.player.shootCooldown = 0;

  state.enemy.x = 10.2;
  state.enemy.y = 9.2;
  state.enemy.hp = 100;
  state.enemy.alive = true;
  state.enemy.fireCooldown = 0;
  state.enemy.patrolAngle = -Math.PI / 2;
  state.enemy.lastSeenX = state.player.x;
  state.enemy.lastSeenY = state.player.y;
  state.enemy.roamX = 10.2;
  state.enemy.roamY = 9.2;
  state.enemy.repathTimer = 0;
  state.enemy.stuckTime = 0;
  state.enemy.path = [];
  state.enemy.pathIndex = 0;
  state.enemy.goalCellX = toCell(state.enemy.roamX);
  state.enemy.goalCellY = toCell(state.enemy.roamY);

  state.bullets = [];
  state.stats.shots = 0;
  state.stats.hits = 0;

  state.gameOver = false;
  state.win = false;
  setStatus("New round started.");
}

function castRay(originX, originY, angle, maxDepth = MAX_DEPTH) {
  const sin = Math.sin(angle);
  const cos = Math.cos(angle);
  let depth = 0;
  const step = 0.02;

  while (depth < maxDepth) {
    depth += step;
    const x = originX + cos * depth;
    const y = originY + sin * depth;
    if (isWall(x, y)) {
      return { hit: true, depth, x, y };
    }
  }
  return { hit: false, depth: maxDepth, x: originX + cos * maxDepth, y: originY + sin * maxDepth };
}

function canSeeTarget(fromX, fromY, toX, toY) {
  const dx = toX - fromX;
  const dy = toY - fromY;
  const distance = Math.hypot(dx, dy);
  if (distance <= 0.001) return true;
  const ray = castRay(fromX, fromY, Math.atan2(dy, dx), distance);
  return !ray.hit || ray.depth + 0.03 >= distance;
}

function tryMove(entity, nx, ny) {
  const oldX = entity.x;
  const oldY = entity.y;
  const radius = 0.2;
  if (!isWall(nx - radius, entity.y) && !isWall(nx + radius, entity.y)) {
    entity.x = nx;
  }
  if (!isWall(entity.x, ny - radius) && !isWall(entity.x, ny + radius)) {
    entity.y = ny;
  }
  return Math.hypot(entity.x - oldX, entity.y - oldY) > 0.0005;
}

function spawnBullet(owner, x, y, z, angle, pitch, damage) {
  state.bullets.push({
    owner,
    x,
    y,
    z,
    vx: Math.cos(angle) * BULLET_SPEED,
    vy: Math.sin(angle) * BULLET_SPEED,
    vz: Math.tan(pitch) * BULLET_SPEED,
    life: BULLET_LIFE,
    damage,
  });
}

function endWithWin() {
  state.enemy.alive = false;
  state.gameOver = true;
  state.win = true;
  setStatus("You win! Press R to restart.", 99);
}

function endWithLoss() {
  state.gameOver = true;
  state.win = false;
  setStatus("You were defeated. Press R to restart.", 99);
}

function playerShoot() {
  if (state.player.shootCooldown > 0 || state.gameOver) return;
  state.player.shootCooldown = 0.28;
  state.stats.shots += 1;

  if (!state.enemy.alive) {
    setStatus("No target left.");
    return;
  }
  const muzzleX = state.player.x + Math.cos(state.player.angle) * 0.28;
  const muzzleY = state.player.y + Math.sin(state.player.angle) * 0.28;
  spawnBullet(
    "player",
    muzzleX,
    muzzleY,
    PLAYER_EYE_HEIGHT,
    state.player.angle,
    state.player.pitch,
    PLAYER_DAMAGE
  );
}

function enemyMove(dt, visible, angleToPlayer, dist) {
  const enemy = state.enemy;
  if (!enemy.alive) return;

  if (visible) {
    enemy.lastSeenX = state.player.x;
    enemy.lastSeenY = state.player.y;
    enemy.patrolAngle = angleToPlayer;
    enemy.repathTimer = 0;
  } else {
    enemy.repathTimer -= dt;
    const roamReached = Math.hypot(enemy.roamX - enemy.x, enemy.roamY - enemy.y) < 0.45;
    if (enemy.repathTimer <= 0 || roamReached) {
      const roam = pickEnemyRoamTarget();
      enemy.roamX = roam.x;
      enemy.roamY = roam.y;
      enemy.repathTimer = 1.6 + Math.random() * 1.4;
    }
  }

  const hasLastSeenTarget = Math.hypot(enemy.lastSeenX - enemy.x, enemy.lastSeenY - enemy.y) > 0.55;
  const goalX = visible ? state.player.x : hasLastSeenTarget ? enemy.lastSeenX : enemy.roamX;
  const goalY = visible ? state.player.y : hasLastSeenTarget ? enemy.lastSeenY : enemy.roamY;
  const goalCellX = toCell(goalX);
  const goalCellY = toCell(goalY);

  enemy.repathTimer -= dt;
  const needRepath =
    enemy.repathTimer <= 0 ||
    enemy.path.length === 0 ||
    enemy.goalCellX !== goalCellX ||
    enemy.goalCellY !== goalCellY ||
    enemy.pathIndex >= enemy.path.length;
  if (needRepath) {
    enemy.path = buildPath(enemy.x, enemy.y, goalX, goalY);
    enemy.pathIndex = enemy.path.length > 1 ? 1 : 0;
    enemy.goalCellX = goalCellX;
    enemy.goalCellY = goalCellY;
    enemy.repathTimer = ENEMY_REPATH_INTERVAL_SEC;
  }

  let target = enemy.path[enemy.pathIndex];
  if (!target) {
    target = { x: goalX, y: goalY };
  }

  const distToTarget = Math.hypot(target.x - enemy.x, target.y - enemy.y);
  if (distToTarget < 0.2 && enemy.pathIndex < enemy.path.length - 1) {
    enemy.pathIndex += 1;
    target = enemy.path[enemy.pathIndex];
  }

  let desiredAngle = Math.atan2(target.y - enemy.y, target.x - enemy.x);
  const speed = visible ? 1.35 : 1.05;
  if (dist < 1.1 && visible) {
    desiredAngle += Math.PI;
  }

  const nx = enemy.x + Math.cos(desiredAngle) * dt * speed;
  const ny = enemy.y + Math.sin(desiredAngle) * dt * speed;
  const moved = tryMove(enemy, nx, ny);
  if (moved) {
    enemy.patrolAngle = desiredAngle;
  }

  if (moved) {
    enemy.stuckTime = 0;
    return;
  }

  enemy.stuckTime += dt;
  if (enemy.stuckTime > ENEMY_STUCK_RECOVER_SEC) {
    const roam = pickEnemyRoamTarget();
    enemy.roamX = roam.x;
    enemy.roamY = roam.y;
    enemy.lastSeenX = roam.x;
    enemy.lastSeenY = roam.y;
    enemy.path = [];
    enemy.pathIndex = 0;
    enemy.repathTimer = 0;
    enemy.stuckTime = 0;
  }
}

function enemyUpdate(dt) {
  const enemy = state.enemy;
  const player = state.player;
  if (!enemy.alive || state.gameOver) return;

  const dx = player.x - enemy.x;
  const dy = player.y - enemy.y;
  const dist = Math.hypot(dx, dy);
  const angleToPlayer = Math.atan2(dy, dx);
  const visible = canSeeTarget(enemy.x, enemy.y, player.x, player.y);
  enemyMove(dt, visible, angleToPlayer, dist);

  enemy.fireCooldown = Math.max(0, enemy.fireCooldown - dt);
  if (visible && dist < 5.2 && enemy.fireCooldown <= 0) {
    enemy.fireCooldown = 0.8;
    const spread = (Math.random() - 0.5) * 0.08;
    const verticalSpread = (Math.random() - 0.5) * 0.03;
    const enemyEyeZ = ENEMY_BASE_Z + ENEMY_HEIGHT * 0.58;
    const pitchToPlayer = Math.atan2(PLAYER_EYE_HEIGHT - enemyEyeZ, Math.max(0.001, dist));
    const muzzleX = enemy.x + Math.cos(angleToPlayer) * 0.22;
    const muzzleY = enemy.y + Math.sin(angleToPlayer) * 0.22;
    spawnBullet("enemy", muzzleX, muzzleY, enemyEyeZ, angleToPlayer + spread, pitchToPlayer + verticalSpread, ENEMY_DAMAGE);
  }
}

function updateBullets(dt) {
  for (let i = state.bullets.length - 1; i >= 0; i--) {
    const bullet = state.bullets[i];
    bullet.x += bullet.vx * dt;
    bullet.y += bullet.vy * dt;
    bullet.z += bullet.vz * dt;
    bullet.life -= dt;

    if (isWall(bullet.x, bullet.y) || bullet.life <= 0) {
      state.bullets.splice(i, 1);
      continue;
    }

    if (bullet.owner === "player" && state.enemy.alive) {
      const hitEnemy = Math.hypot(bullet.x - state.enemy.x, bullet.y - state.enemy.y) < 0.26;
      const hitEnemyHeight = bullet.z >= ENEMY_BASE_Z && bullet.z <= ENEMY_BASE_Z + ENEMY_HEIGHT;
      if (hitEnemy && hitEnemyHeight) {
        state.bullets.splice(i, 1);
        state.stats.hits += 1;
        state.enemy.hp = Math.max(0, state.enemy.hp - bullet.damage);
        setStatus(`Hit! Enemy -${bullet.damage} HP`, 0.5);
        if (state.enemy.hp <= 0) {
          endWithWin();
        }
      }
      continue;
    }

    if (bullet.owner === "enemy" && state.player.hp > 0) {
      const hitPlayer = Math.hypot(bullet.x - state.player.x, bullet.y - state.player.y) < 0.23;
      const hitPlayerHeight = bullet.z >= 0 && bullet.z <= PLAYER_HEIGHT;
      if (hitPlayer && hitPlayerHeight) {
        state.bullets.splice(i, 1);
        state.player.hp = Math.max(0, state.player.hp - bullet.damage);
        setStatus(`Enemy hit you for ${bullet.damage} HP.`, 0.6);
        if (state.player.hp <= 0) {
          endWithLoss();
        }
      }
    }
  }
}

function update(dt) {
  const player = state.player;
  const keys = state.keys;

  if (keys["ArrowLeft"]) {
    player.angle = normalizeAngle(player.angle - TURN_SPEED * dt);
  }
  if (keys["ArrowRight"]) {
    player.angle = normalizeAngle(player.angle + TURN_SPEED * dt);
  }

  const forward = (keys["KeyW"] || keys["ArrowUp"] ? 1 : 0) - (keys["KeyS"] || keys["ArrowDown"] ? 1 : 0);
  const strafe = (keys["KeyD"] ? 1 : 0) - (keys["KeyA"] ? 1 : 0);
  if ((forward !== 0 || strafe !== 0) && !state.gameOver) {
    const moveX = Math.cos(player.angle) * forward - Math.sin(player.angle) * strafe;
    const moveY = Math.sin(player.angle) * forward + Math.cos(player.angle) * strafe;
    const len = Math.hypot(moveX, moveY) || 1;
    const nx = player.x + (moveX / len) * MOVE_SPEED * dt;
    const ny = player.y + (moveY / len) * MOVE_SPEED * dt;
    tryMove(player, nx, ny);
  }

  player.shootCooldown = Math.max(0, player.shootCooldown - dt);
  enemyUpdate(dt);
  updateBullets(dt);

  if (state.messageTimer > 0 && state.messageTimer < 90) {
    state.messageTimer = Math.max(0, state.messageTimer - dt);
    if (state.messageTimer === 0 && !state.gameOver) {
      statusEl.textContent = "Track the target and land your shots.";
    }
  }
}

function renderWalls() {
  const width = canvas.width;
  const height = canvas.height;
  const halfHeight = height / 2;
  const pitchPx = state.player.pitch * height * 0.35;
  const horizon = halfHeight + pitchPx;

  const skyGradient = ctx.createLinearGradient(0, 0, 0, Math.max(1, horizon));
  skyGradient.addColorStop(0, "#6ba6ff");
  skyGradient.addColorStop(1, "#22305d");
  ctx.fillStyle = skyGradient;
  ctx.fillRect(0, 0, width, horizon);

  const floorGradient = ctx.createLinearGradient(0, horizon, 0, height);
  floorGradient.addColorStop(0, "#252525");
  floorGradient.addColorStop(1, "#0d0d0d");
  ctx.fillStyle = floorGradient;
  ctx.fillRect(0, horizon, width, height - horizon);

  const zBuffer = [];
  for (let col = 0; col < width; col++) {
    const rayScreenPos = col / width;
    const rayAngle = state.player.angle - HALF_FOV + rayScreenPos * FOV;
    const ray = castRay(state.player.x, state.player.y, rayAngle);
    const correctedDepth = ray.depth * Math.cos(rayAngle - state.player.angle);
    zBuffer[col] = correctedDepth;

    const wallHeight = Math.min(height, (height / Math.max(correctedDepth, 0.01)) * 0.8);
    const top = horizon - wallHeight / 2;
    const shade = Math.max(30, 220 - correctedDepth * 22);

    ctx.fillStyle = `rgb(${shade}, ${shade}, ${shade + 20})`;
    ctx.fillRect(col, top, 1, wallHeight);
  }

  return zBuffer;
}

function renderEnemy(zBuffer) {
  if (!state.enemy.alive) return;

  const dx = state.enemy.x - state.player.x;
  const dy = state.enemy.y - state.player.y;
  const dist = Math.hypot(dx, dy);
  const angleToEnemy = Math.atan2(dy, dx);
  const angleDiff = normalizeAngle(angleToEnemy - state.player.angle);

  if (Math.abs(angleDiff) > HALF_FOV + 0.25) return;
  if (!canSeeTarget(state.player.x, state.player.y, state.enemy.x, state.enemy.y)) return;

  const screenX = (angleDiff / FOV + 0.5) * canvas.width;
  const spriteHeight = Math.min(canvas.height * 0.85, (canvas.height / dist) * 0.95);
  const spriteWidth = spriteHeight * 0.5;
  const left = Math.floor(screenX - spriteWidth / 2);
  const right = Math.floor(screenX + spriteWidth / 2);
  const horizon = canvas.height / 2 + state.player.pitch * canvas.height * 0.35;
  const projectionScale = canvas.height * 0.75;
  const enemyCenterZ = ENEMY_BASE_Z + ENEMY_HEIGHT * 0.5;
  const centerY = horizon - ((enemyCenterZ - PLAYER_EYE_HEIGHT) / Math.max(0.001, dist)) * projectionScale;
  const top = centerY - spriteHeight / 2;

  for (let x = left; x < right; x++) {
    if (x < 0 || x >= canvas.width) continue;
    if (dist > zBuffer[x]) continue;
    const t = (x - left) / Math.max(1, right - left);
    const red = Math.floor(220 - t * 40);
    ctx.fillStyle = `rgb(${red}, 60, 65)`;
    ctx.fillRect(x, top, 1, spriteHeight);
  }

  // Head marker.
  ctx.fillStyle = "#f8d9be";
  ctx.beginPath();
  ctx.arc(screenX, top + spriteHeight * 0.2, spriteWidth * 0.16, 0, Math.PI * 2);
  ctx.fill();
}

function renderProjectiles(zBuffer) {
  const bullets = [...state.bullets].sort((a, b) => {
    const da = Math.hypot(a.x - state.player.x, a.y - state.player.y);
    const db = Math.hypot(b.x - state.player.x, b.y - state.player.y);
    return db - da;
  });

  for (const bullet of bullets) {
    const dx = bullet.x - state.player.x;
    const dy = bullet.y - state.player.y;
    const dist = Math.hypot(dx, dy);
    if (dist <= 0.05) continue;

    const angleToBullet = Math.atan2(dy, dx);
    const angleDiff = normalizeAngle(angleToBullet - state.player.angle);
    if (Math.abs(angleDiff) > HALF_FOV + 0.2) continue;

    const screenX = (angleDiff / FOV + 0.5) * canvas.width;
    const col = Math.floor(screenX);
    if (col < 0 || col >= canvas.width) continue;
    if (dist > zBuffer[col]) continue;

    const size = Math.min(14, Math.max(3, (canvas.height / dist) * 0.03));
    const horizon = canvas.height / 2 + state.player.pitch * canvas.height * 0.35;
    const projectionScale = canvas.height * 0.75;
    const y = horizon - ((bullet.z - PLAYER_EYE_HEIGHT) / Math.max(0.001, dist)) * projectionScale;

    ctx.fillStyle = bullet.owner === "player" ? "#ffe768" : "#ff9c79";
    ctx.beginPath();
    ctx.arc(screenX, y, size, 0, Math.PI * 2);
    ctx.fill();
  }
}

function renderMiniMap() {
  const cell = 8;
  const mapW = MAP[0].length * cell;
  const mapH = MAP.length * cell;
  const pad = 16;
  const x0 = canvas.width - mapW - pad;
  const y0 = 108;

  ctx.fillStyle = "rgba(12, 18, 34, 0.72)";
  ctx.fillRect(x0 - 6, y0 - 6, mapW + 12, mapH + 12);
  for (let y = 0; y < MAP.length; y++) {
    for (let x = 0; x < MAP[0].length; x++) {
      ctx.fillStyle = MAP[y][x] === "1" ? "rgba(205, 220, 255, 0.65)" : "rgba(38, 53, 90, 0.55)";
      ctx.fillRect(x0 + x * cell, y0 + y * cell, cell - 1, cell - 1);
    }
  }

  ctx.fillStyle = "#6cf1b2";
  ctx.beginPath();
  ctx.arc(x0 + state.player.x * cell, y0 + state.player.y * cell, 3, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = "#6cf1b2";
  ctx.beginPath();
  ctx.moveTo(x0 + state.player.x * cell, y0 + state.player.y * cell);
  ctx.lineTo(
    x0 + (state.player.x + Math.cos(state.player.angle) * 0.8) * cell,
    y0 + (state.player.y + Math.sin(state.player.angle) * 0.8) * cell
  );
  ctx.stroke();

  if (state.enemy.alive) {
    ctx.fillStyle = "#ff535d";
    ctx.beginPath();
    ctx.arc(x0 + state.enemy.x * cell, y0 + state.enemy.y * cell, 3, 0, Math.PI * 2);
    ctx.fill();
  }
}

function renderHud() {
  const playerPct = Math.max(0, (state.player.hp / 100) * 100);
  const enemyPct = Math.max(0, (state.enemy.hp / 100) * 100);

  playerHpEl.textContent = String(state.player.hp);
  enemyHpEl.textContent = String(state.enemy.hp);
  playerHpBarEl.style.width = `${playerPct}%`;
  enemyHpBarEl.style.width = `${enemyPct}%`;
  shotsCountEl.textContent = String(state.stats.shots);
  hitsCountEl.textContent = String(state.stats.hits);
  cooldownTextEl.textContent = `${state.player.shootCooldown.toFixed(2)}s`;

  ctx.strokeStyle = "rgba(240, 245, 255, 0.85)";
  ctx.lineWidth = 2;
  const cx = canvas.width / 2;
  const cy = canvas.height / 2;
  ctx.beginPath();
  ctx.moveTo(cx - 12, cy);
  ctx.lineTo(cx + 12, cy);
  ctx.moveTo(cx, cy - 12);
  ctx.lineTo(cx, cy + 12);
  ctx.stroke();

  if (state.gameOver) {
    overlay.style.background = "rgba(0,0,0,0.35)";
  } else {
    overlay.style.background = "transparent";
  }
}

function render() {
  const zBuffer = renderWalls();
  renderEnemy(zBuffer);
  renderProjectiles(zBuffer);
  renderHud();
  renderMiniMap();
}

let prevTime = performance.now();
function frame(ts) {
  const dt = Math.min(0.05, (ts - prevTime) / 1000);
  prevTime = ts;
  update(dt);
  render();
  requestAnimationFrame(frame);
}

window.addEventListener("keydown", (e) => {
  state.keys[e.code] = true;
  if (e.code.startsWith("Arrow") || ["KeyW", "KeyA", "KeyS", "KeyD", "Space"].includes(e.code)) {
    e.preventDefault();
  }
  if (e.code === "Space") {
    e.preventDefault();
    playerShoot();
  }
  if (e.code === "KeyR" && state.gameOver) {
    resetGame();
  }
});

window.addEventListener("keyup", (e) => {
  state.keys[e.code] = false;
});

canvas.addEventListener("click", () => {
  if (document.pointerLockElement !== canvas) {
    canvas.requestPointerLock();
  }
});

window.addEventListener("mousemove", (e) => {
  if (document.pointerLockElement === canvas) {
    state.player.angle = normalizeAngle(state.player.angle + e.movementX * MOUSE_SENSITIVITY);
    state.player.pitch -= e.movementY * MOUSE_PITCH_SENSITIVITY;
    state.player.pitch = Math.max(-MAX_PITCH, Math.min(MAX_PITCH, state.player.pitch));
  }
});

window.addEventListener("pointerlockchange", () => {
  if (document.pointerLockElement === canvas) {
    setStatus("Mouse aim enabled. Press Esc to release cursor.", 1.5);
  } else if (!state.gameOver) {
    setStatus("Click game view to lock cursor for mouse aim.", 1.5);
  }
});

setStatus("WASD move, mouse aim, Space shoot. Click game to lock cursor.");
requestAnimationFrame(frame);
