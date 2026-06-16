/*
 * Phase 0 — build-bookmarklet.mjs
 * indexer.js + oracle.js + measure.js 를 하나로 합쳐 북마클릿(javascript: URL)과
 * 드래그-설치 페이지(install.html) 를 생성한다.
 *
 * 사용법:  node build-bookmarklet.mjs
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const read = (f) => readFileSync(join(here, f), 'utf8');

// 순서 중요: indexer → oracle → measure(=P0.run 정의) → 실행
const body = [read('indexer.js'), read('oracle.js'), read('measure.js'), 'window.__P0.run();'].join('\n;\n');

const bookmarklet = 'javascript:' + encodeURIComponent('(function(){' + body + '})();');

writeFileSync(join(here, 'bookmarklet.txt'), bookmarklet + '\n', 'utf8');

const html = `<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Phase 0 측정 도구 설치</title>
<style>
  body { font-family: -apple-system, "Apple SD Gothic Neo", sans-serif; max-width: 720px; margin: 40px auto; padding: 0 16px; line-height: 1.7; color: #222; }
  h1 { font-size: 22px; }
  .bm { display:inline-block; padding:10px 18px; background:#1a73e8; color:#fff !important; border-radius:8px; text-decoration:none; font-weight:700; font-size:16px; }
  .step { background:#f6f8fa; border:1px solid #e1e4e8; border-radius:8px; padding:14px 18px; margin:14px 0; }
  code { background:#eef; padding:1px 5px; border-radius:4px; }
  .warn { color:#b25000; }
</style>
</head>
<body>
  <h1>scourt 측정 도구 (Phase 0)</h1>
  <p>이 버튼을 <b>브라우저 즐겨찾기(북마크) 막대로 드래그</b>해서 설치하세요.</p>
  <p style="margin:24px 0;"><a class="bm" href="${bookmarklet.replace(/"/g, '&quot;')}">📏 scourt 측정</a></p>

  <div class="step">
    <b>설치가 안 되면 (드래그가 막힌 경우):</b><br>
    북마크를 새로 만들고(아무 페이지나 ☆), 이름은 <code>scourt 측정</code>, 주소(URL)칸에는
    같은 폴더의 <code>bookmarklet.txt</code> 내용을 통째로 붙여넣으세요.
  </div>

  <h2>쓰는 법</h2>
  <ol>
    <li>scourt 에 <b>평소처럼 공동인증서로 로그인</b>합니다.</li>
    <li>측정할 화면으로 이동합니다 (예: 사건검색 입력폼).</li>
    <li class="warn">표/그리드 화면이면 <b>데이터가 1줄 이상 뜬 뒤, 맨 위로 스크롤</b>한 상태에서 누르세요.</li>
    <li>즐겨찾기의 <b>「scourt 측정」</b>을 클릭합니다.</li>
    <li>"리포트가 클립보드에 복사됨" 메시지가 뜨면, <b>Claude 대화창에 그대로 붙여넣기(Ctrl+V)</b> 하면 끝.</li>
  </ol>
  <p class="warn">⚠️ 측정만 합니다. 아무것도 클릭하거나 제출하지 않습니다(읽기 전용).</p>
</body>
</html>
`;
writeFileSync(join(here, 'install.html'), html, 'utf8');

console.log('built: bookmarklet.txt (' + bookmarklet.length + ' chars), install.html');
