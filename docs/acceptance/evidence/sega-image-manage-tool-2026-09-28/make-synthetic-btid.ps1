param(
    [string]$SourceRoot = 'D:\ALL.NET\SegaImageManageTool',
    [string]$OutputPath = (Join-Path $PSScriptRoot 'synthetic-valid.PACK')
)
$ErrorActionPreference = 'Stop'
# Synthetic zero-filled image; no game data. Constants are read from the existing parser.
$source = Get-Content -LiteralPath (Join-Path $SourceRoot 'Modules\Btid.cs') -Raw
$key = [Convert]::FromHexString([regex]::Match($source, 'byte\[\] key = Common.HexStringToByteArray\("([0-9a-fA-F]+)"\)').Groups[1].Value)
$iv = [Convert]::FromHexString([regex]::Match($source, 'byte\[\] iv = Common.HexStringToByteArray\("([0-9a-fA-F]+)"\)').Groups[1].Value)
$hmacKey = [Convert]::FromHexString([regex]::Match($source, 'byte\[\] hmacKey = Common.HexStringToByteArray\("([0-9a-fA-F]+)"\)').Groups[1].Value)
Add-Type -TypeDefinition @'
public static class SyntheticBtidCrc {
    public static uint Compute(byte[] data, int offset, int length, uint last = 0) {
        uint value = last ^ 0xffffffff;
        for (int i = offset; i < offset + length; i++) {
            value ^= data[i];
            for (int b = 0; b < 8; b++) value = (value >> 1) ^ ((value & 1) == 1 ? 0xedb88320u : 0);
        }
        return value ^ 0xffffffff;
    }
}
'@
$header = [byte[]]::new(0x2800)
$stream = [IO.MemoryStream]::new($header, $true)
$writer = [IO.BinaryWriter]::new($stream)
$writer.Write([uint32]0)
$writer.Write([uint32]0x2800)
$writer.Write([Text.Encoding]::ASCII.GetBytes('BTID'))
$writer.Write([byte]0)
$writer.Write([byte]0)
$writer.Write([uint16]0)
$writer.Write([Text.Encoding]::ASCII.GetBytes('TEST'))
$writer.Write([uint16]2026)
foreach ($value in @(9,28,10,50,0)) { $writer.Write([byte]$value) }
# Parse() consumes five version bytes (the legacy Write() uses a different width).
foreach ($value in @(1,3,2,1,0)) { $writer.Write([byte]$value) }
$writer.Write([uint64]2)
$writer.Write([uint64]0x4000)
$writer.Write([uint64]1)
$writer.Flush()
$crc = [SyntheticBtidCrc]::Compute($header,4,$header.Length-4)
[BitConverter]::GetBytes($crc).CopyTo($header,0)
$writer.Dispose()
$aes = [Security.Cryptography.Aes]::Create()
$aes.Key = $key
$aes.IV = $iv
$aes.Mode = [Security.Cryptography.CipherMode]::CBC
$aes.Padding = [Security.Cryptography.PaddingMode]::None
$encryptor = $aes.CreateEncryptor()
$encrypted = $encryptor.TransformFinalBlock($header,0,$header.Length)
$encryptor.Dispose()
$aes.Dispose()
$data = [byte[]]::new(0x8000)
$encrypted.CopyTo($data,0)
$secondCrc = [SyntheticBtidCrc]::Compute($data,0x4000,0x4000)
[BitConverter]::GetBytes($secondCrc).CopyTo($data,0x2A04)
$firstCrc = [SyntheticBtidCrc]::Compute($data,0,0x2800)
$firstCrc = [SyntheticBtidCrc]::Compute($data,0x2A04,0x4000-0x2A04,$firstCrc)
[BitConverter]::GetBytes($firstCrc).CopyTo($data,0x2A00)
$hmac = [Security.Cryptography.HMACSHA1]::new($hmacKey)
$signature = $hmac.ComputeHash($data,0x2A00,0x4000-0x2A00)
$signature.CopyTo($data,0x2800)
$hmac.Dispose()
[IO.File]::WriteAllBytes($OutputPath,$data)
[ordered]@{
    kind='synthetic_btid_acceptance_fixture'; created_at=[DateTime]::UtcNow.ToString('o')
    path=[IO.Path]::GetFullPath($OutputPath); size=$data.Length
    sha256=(Get-FileHash -LiteralPath $OutputPath -Algorithm SHA256).Hash.ToLowerInvariant()
    game_id='TEST'; version='1.2.3'; header_crc32=$crc; sectors=2; sector_size=0x4000
    synthetic_only=$true; secrets_included=$false
} | ConvertTo-Json
