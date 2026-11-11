"""Run the device's own firmware-update check (SDUpdateReadBinFile) on a firmware image.

The update routine of the application section is executed in a Unicorn ARM emulator with the
SD card / OS calls stubbed out.  It tells whether the device would accept the file (MD5 stage).
Requires: pip install unicorn capstone
"""
import struct

from . import container, profile as prof_mod


def run(data: bytes, profile_name="uc5300p", max_insn=3_000_000_000):
    try:
        from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_READ_UNMAPPED, \
            UC_HOOK_MEM_WRITE_UNMAPPED, UC_HOOK_MEM_FETCH_UNMAPPED, UC_MEM_FETCH_UNMAPPED, UcError
        from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, \
            UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC
        import capstone
        from capstone import arm_const as A
    except ImportError as ex:
        raise SystemExit(f"emulation needs unicorn and capstone ({ex})")
    prof = prof_mod.load(profile_name)
    emu = prof["emulation"]
    lay = container.parse(data)
    sec = lay.sections[prof["app_section"] - 1]
    H = lambda k: prof_mod.num(prof, "emulation", k)          # file offsets of the stock image
    R = sec.ram                                                 # file offset -> RAM address
    payload = data[sec.payload_off:sec.payload_end]
    mu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    b0 = sec.load & ~0xFFF
    mu.mem_map(b0, (sec.size + 0xFFF + (sec.load - b0) + 0x2000000) & ~0xFFF)
    mu.mem_write(sec.load, payload)
    STACK = 0x20000000 + 0x200000
    mu.mem_map(0x20000000, 0x400000)
    LR = 0x23000000
    mu.mem_map(LR, 0x1000)
    func, fsize = H("func_file_off"), H("func_size")
    md = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
    real = {R(int(x, 0)) for x in emu["md5_funcs"]}
    targets = set()
    code = data[func:func + fsize]
    for ins in md.disasm(code, R(func)):
        if ins.id in (A.ARM_INS_BL, A.ARM_INS_BLX) and ins.op_str.startswith("#"):
            targets.add(int(ins.op_str.lstrip("#"), 0))
    stub = {t for t in targets if t not in real} | {R(int(x, 0)) for x in emu["extra_stubs"]}
    for t in stub:
        if not (b0 <= t < b0 + sec.size + 0x2000000):
            try:
                mu.mem_map(t & ~0xFFF, 0x1000)
            except Exception:
                pass
    ready, getsize, seek, read = (R(H(k)) for k in ("stub_ready", "stub_size", "stub_seek", "stub_read"))
    state = {"pos": 0, "res": None}

    def stubh(uc, addr, size, _):
        r0, r1, r2, r3 = (uc.reg_read(x) for x in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3))
        ret = 0
        if addr == ready:
            ret = 1
        elif addr == getsize:
            uc.mem_write(r1, struct.pack("<I", len(data)))
        elif addr == seek:
            state["pos"] = r1
        elif addr == read:
            n = min(r2, len(data) - state["pos"])
            uc.mem_write(r1, data[state["pos"]:state["pos"] + n])
            state["pos"] += n
            uc.mem_write(r3, struct.pack("<I", n))
        uc.reg_write(UC_ARM_REG_R0, ret)
        uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))

    def mark(text):
        def h(uc, addr, size, _):
            state["res"] = text
            uc.emu_stop()
        return h

    for t in stub:
        mu.hook_add(UC_HOOK_CODE, stubh, begin=t, end=t)
    for key, text in (("md5_fail", "FAIL MD5 mismatch - the device would reject this file"),
                      ("md5_ok", "OK header MD5 accepted, update proceeds to flashing"),
                      ("early_fail", "FAIL bad magic or size")):
        a = R(H(key))
        mu.hook_add(UC_HOOK_CODE, mark(text), begin=a, end=a)

    def unm(uc, access, addr, size, value, ud):
        try:
            uc.mem_map(addr & ~0xFFF, 0x1000)
            if access == UC_MEM_FETCH_UNMAPPED:
                uc.mem_write(addr, b"\x1e\xff\x2f\xe1")      # bx lr
        except Exception:
            pass
        return True

    mu.hook_add(UC_HOOK_MEM_READ_UNMAPPED | UC_HOOK_MEM_WRITE_UNMAPPED | UC_HOOK_MEM_FETCH_UNMAPPED, unm)
    mu.reg_write(UC_ARM_REG_R0, 1)
    mu.reg_write(UC_ARM_REG_SP, STACK)
    mu.reg_write(UC_ARM_REG_LR, LR)
    try:
        mu.emu_start(R(func), LR, count=max_insn)
    except UcError as ex:
        return f"FAIL emulator error: {ex}"
    return state["res"] or "FAIL emulation ended without a verdict"
