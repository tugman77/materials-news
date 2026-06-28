// 소재타임스 문의 모달 — Telegram 봇으로 즉시 전송
(function () {
  const BOT = '8860516747:AAGikwdjA120Jy8Dei9_IFVCFh4l3LudruI';
  const CID = '6625834513';

  /* ── CSS ── */
  const s = document.createElement('style');
  s.textContent = `
    #cm-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:9999;align-items:center;justify-content:center;padding:16px}
    #cm-overlay.open{display:flex}
    #cm-box{background:#fff;width:100%;max-width:460px;border-top:4px solid #c8102e;padding:28px 28px 22px;position:relative;max-height:90vh;overflow-y:auto;box-sizing:border-box}
    #cm-close{position:absolute;top:13px;right:16px;background:none;border:none;font-size:20px;cursor:pointer;color:#aaa;line-height:1}
    #cm-close:hover{color:#333}
    #cm-title{font-size:17px;font-weight:700;color:#1a2b4a;margin-bottom:20px}
    .cm-row{margin-bottom:13px}
    .cm-row label{display:block;font-size:12px;font-weight:700;color:#555;margin-bottom:5px;letter-spacing:.3px}
    .cm-row input,.cm-row select,.cm-row textarea{width:100%;border:1px solid #d8d8d2;padding:9px 11px;font-size:14px;font-family:inherit;outline:none;box-sizing:border-box;border-radius:0;background:#fff}
    .cm-row input:focus,.cm-row select:focus,.cm-row textarea:focus{border-color:#1a2b4a}
    .cm-row textarea{resize:vertical;min-height:110px}
    .cm-opt{font-size:11px;color:#aaa;font-weight:400}
    #cm-btn{background:#1a2b4a;color:#fff;border:none;width:100%;padding:12px;font-size:14px;font-weight:700;cursor:pointer;margin-top:4px;letter-spacing:.3px}
    #cm-btn:hover{background:#c8102e}
    #cm-btn:disabled{background:#bbb;cursor:not-allowed}
    #cm-feedback{font-size:13px;text-align:center;min-height:18px;margin-top:10px}
    #cm-feedback.ok{color:#1a7a3a}
    #cm-feedback.err{color:#c8102e}
  `;
  document.head.appendChild(s);

  /* ── HTML ── */
  const wrap = document.createElement('div');
  wrap.id = 'cm-overlay';
  wrap.innerHTML = `
    <div id="cm-box">
      <button id="cm-close" onclick="closeContactModal()" aria-label="닫기">✕</button>
      <div id="cm-title">문의하기</div>
      <div class="cm-row">
        <label>문의 유형</label>
        <select id="cm-type">
          <option>광고 문의</option>
          <option>기사 제보</option>
          <option>오류 신고</option>
          <option>기타</option>
        </select>
      </div>
      <div class="cm-row">
        <label>이름 <span class="cm-opt">(선택)</span></label>
        <input id="cm-name" type="text" placeholder="홍길동" autocomplete="name">
      </div>
      <div class="cm-row">
        <label>연락처 <span class="cm-opt">(이메일·전화 중 하나, 선택)</span></label>
        <input id="cm-contact" type="text" placeholder="example@email.com">
      </div>
      <div class="cm-row">
        <label>문의 내용 <span style="color:#c8102e">*</span></label>
        <textarea id="cm-body" placeholder="문의 내용을 자유롭게 입력해 주세요."></textarea>
      </div>
      <button id="cm-btn" onclick="submitContact()">보내기</button>
      <div id="cm-feedback"></div>
    </div>
  `;
  document.body.appendChild(wrap);

  wrap.addEventListener('click', function (e) {
    if (e.target === wrap) closeContactModal();
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeContactModal();
  });

  /* ── 공개 API ── */
  window.openContactModal = function (type) {
    wrap.classList.add('open');
    if (type) {
      const sel = document.getElementById('cm-type');
      for (let i = 0; i < sel.options.length; i++) {
        if (sel.options[i].value === type) { sel.selectedIndex = i; break; }
      }
    }
    document.getElementById('cm-feedback').textContent = '';
    document.getElementById('cm-body').focus();
  };

  window.closeContactModal = function () {
    wrap.classList.remove('open');
  };

  window.submitContact = async function () {
    const type    = document.getElementById('cm-type').value;
    const name    = document.getElementById('cm-name').value.trim();
    const contact = document.getElementById('cm-contact').value.trim();
    const body    = document.getElementById('cm-body').value.trim();
    const fb      = document.getElementById('cm-feedback');
    const btn     = document.getElementById('cm-btn');

    fb.className = '';
    if (!body) { fb.className = 'err'; fb.textContent = '문의 내용을 입력해 주세요.'; return; }

    btn.disabled = true;
    btn.textContent = '전송 중...';

    const lines = [
      '📬 <b>[소재타임스 문의]</b>',
      `유형: ${type}`,
      name    ? `이름: ${name}` : '',
      contact ? `연락처: ${contact}` : '',
      '',
      body,
    ].filter((l, i) => i < 4 || l !== '').join('\n');

    try {
      const res = await fetch(
        `https://api.telegram.org/bot${BOT}/sendMessage`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ chat_id: CID, text: lines, parse_mode: 'HTML' }),
        }
      );
      if (!res.ok) throw new Error();
      fb.className = 'ok';
      fb.textContent = '문의가 접수되었습니다. 빠르게 답변드리겠습니다.';
      document.getElementById('cm-name').value    = '';
      document.getElementById('cm-contact').value = '';
      document.getElementById('cm-body').value    = '';
      setTimeout(closeContactModal, 2200);
    } catch {
      fb.className = 'err';
      fb.textContent = '전송에 실패했습니다. 잠시 후 다시 시도해 주세요.';
    } finally {
      btn.disabled = false;
      btn.textContent = '보내기';
    }
  };
})();
