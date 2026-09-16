/**
 * 跨平台原子檔案寫入模組 (Cross-Platform Atomic File Writer)
 * 抽取自 LINE / Telegram bridge 之 writeStateAtomic 實作
 */

'use strict';

const fs = require('fs');

function writeStateAtomic(targetFilePath, data, maxRetries = 5, baseDelayMs = 100) {
  const tmpFilePath = targetFilePath + '.' + process.pid + '.tmp';
  let attempt = 0;

  while (attempt < maxRetries) {
    try {
      // 先寫入暫存檔
      fs.writeFileSync(tmpFilePath, data, 'utf8');
      // 原子更名 (Windows 若目標存在且被鎖，可能拋錯)
      fs.renameSync(tmpFilePath, targetFilePath);
      return true;
    } catch (err) {
      attempt++;
      if (fs.existsSync(tmpFilePath)) {
        try { fs.unlinkSync(tmpFilePath); } catch (e) {}
      }
      if (attempt >= maxRetries) {
        console.error(`[AtomicWrite] 放棄寫入 ${targetFilePath}，已重試 ${maxRetries} 次。錯誤: ${err.message}`);
        throw err;
      }
      const delay = baseDelayMs * Math.pow(2, attempt) + Math.random() * 50;
      console.warn(`[AtomicWrite] 檔案鎖死，${Math.round(delay)}ms 後重試 (${attempt}/${maxRetries}): ${targetFilePath}`);
      // 使用同步等待達成退避
      const waitTill = new Date(new Date().getTime() + delay);
      while (waitTill > new Date()) {}
    }
  }
  return false;
}

module.exports = { writeStateAtomic };
