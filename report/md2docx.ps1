# md -> docx (pure PowerShell, ASCII source). Usage:
#   $Docs = 'C:\path\to\docs'
#   $code = [IO.File]::ReadAllText('report\md2docx.ps1',[Text.Encoding]::UTF8); Invoke-Expression $code

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression -ErrorAction SilentlyContinue
Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction SilentlyContinue

$YAHEI = -join [char[]]@(0x5FAE,0x8F6F,0x96C5,0x9ED1)   # Chinese name of Microsoft YaHei

function Esc([string]$s) {
    if ($null -eq $s) { return '' }
    $s = $s.Replace('&','&amp;').Replace('<','&lt;').Replace('>','&gt;').Replace('"','&quot;')
    return $s
}
function Inline([string]$s) {
    $s = Esc $s
    $s = [Regex]::Replace($s, '\*\*(.+?)\*\*', '<w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve">$1</w:t></w:r>')
    $s = [Regex]::Replace($s, '`([^`]+)`', '<w:r><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/><w:sz w:val="18"/></w:rPr><w:t xml:space="preserve">$1</w:t></w:r>')
    $s = [Regex]::Replace($s, '\[(.+?)\]\((.+?)\)', '$1')
    return $s
}
function Para([string]$style, [string]$inner, [string]$extraPPr) {
    $p = '<w:p><w:pPr>'
    if ($style) { $p += '<w:pStyle w:val="' + $style + '"/>' }
    if ($extraPPr) { $p += $extraPPr }
    $p += '</w:pPr>' + $inner + '</w:p>'
    return $p
}
function PlainPara([string]$text, [string]$style) {
    if ($text.Trim() -eq '') { return Para $style '' '' }
    return Para $style (Inline $text) ''
}

function BuildDocument([string]$mdPath) {
    $lines = [IO.File]::ReadAllLines($mdPath, [Text.Encoding]::UTF8)
    $sb = New-Object Text.StringBuilder
    [void]$sb.Append('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>')
    [void]$sb.Append('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><w:body>')
    $i = 0; $firstH1 = $true; $inCode = $false
    while ($i -lt $lines.Count) {
        $ln = $lines[$i]
        if ($ln -match '^\s*```') {
            if (-not $inCode) { $inCode = $true } else { $inCode = $false }
            $i++; continue
        }
        if ($inCode) {
            [void]$sb.Append((Para 'Code' ('<w:r><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/><w:sz w:val="17"/></w:rPr><w:t xml:space="preserve">' + (Esc $ln) + '</w:t></w:r>') ''))
            $i++; continue
        }
        if ($ln -match '^\s*\|.*\|\s*$') {
            $rows = @()
            while ($i -lt $lines.Count -and $lines[$i] -match '^\s*\|.*\|\s*$') { $rows += $lines[$i]; $i++ }
            $data = @($rows | Where-Object { $_ -notmatch '^\s*\|[\s:\-\|]+\|\s*$' })
            if ($data.Count -gt 0) {
                $ncol = 0
                foreach ($r in $data) { $c = ($r.Trim().Trim('|') -split '\|').Count; if ($c -gt $ncol) { $ncol = $c } }
                $w = [int](9526 / [Math]::Max($ncol,1))
                [void]$sb.Append('<w:tbl><w:tblPr><w:tblW w:type="pct" w:w="5000"/><w:tblBorders>')
                foreach ($sd in @('top','left','bottom','right','insideH','insideV')) {
                    [void]$sb.Append('<w:' + $sd + ' w:val="single" w:sz="4" w:space="0" w:color="808080"/>')
                }
                [void]$sb.Append('</w:tblBorders></w:tblPr><w:tblGrid>')
                for ($k=0; $k -lt $ncol; $k++) { [void]$sb.Append('<w:gridCol w:w="' + $w + '"/>') }
                [void]$sb.Append('</w:tblGrid>')
                $r0 = 0
                foreach ($r in $data) {
                    $cells = $r.Trim().Trim('|') -split '\|'
                    [void]$sb.Append('<w:tr>')
                    for ($k=0; $k -lt $ncol; $k++) {
                        $cellText = ''
                        if ($k -lt $cells.Count) { $cellText = $cells[$k].Trim() }
                        [void]$sb.Append('<w:tc><w:tcPr><w:tcW w:type="dxa" w:w="' + $w + '"/>')
                        if ($r0 -eq 0) { [void]$sb.Append('<w:shd w:val="clear" w:color="auto" w:fill="DCE6F2"/>') }
                        [void]$sb.Append('</w:tcPr>')
                        $inner = Inline $cellText
                        if ($r0 -eq 0) { $inner = '<w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve">' + (Esc $cellText) + '</w:t></w:r>' }
                        [void]$sb.Append((Para 'TableText' $inner ''))
                        [void]$sb.Append('</w:tc>')
                    }
                    [void]$sb.Append('</w:tr>')
                    $r0++
                }
                [void]$sb.Append('</w:tbl>')
                [void]$sb.Append((Para 'TableText' '' ''))
            }
            continue
        }
        if ($ln -match '^#{1,4}\s') {
            $lvl = ($ln -replace '^(#+).*$','$1').Length
            $txt = Inline ($ln -replace '^#+\s*','')
            if ($lvl -eq 1 -and $firstH1) {
                [void]$sb.Append((Para 'Heading1' $txt ''))
                $firstH1 = $false
            } elseif ($lvl -eq 1) {
                [void]$sb.Append((Para 'Heading1' $txt '<w:pageBreakBefore/>'))
            } else {
                [void]$sb.Append((Para ('Heading' + $lvl) $txt ''))
            }
            $i++; continue
        }
        if ($ln -match '^\s*[-*]\s+') {
            while ($i -lt $lines.Count -and $lines[$i] -match '^\s*[-*]\s+') {
                $t = $lines[$i] -replace '^\s*[-*]\s+',''
                $t = $t -replace '^\[ \]\s*','[ ] ' -replace '^\[x\]\s*','[x] '
                [void]$sb.Append((Para '' ('<w:r><w:t xml:space="preserve">' + [char]0x2022 + '  </w:t></w:r>' + (Inline $t)) '<w:ind w:left="420" w:hanging="220"/><w:spacing w:after="30"/>'))
                $i++
            }
            continue
        }
        if ($ln -match '^\s*\d+\.\s+') {
            while ($i -lt $lines.Count -and $lines[$i] -match '^\s*\d+\.\s+') {
                $t = $lines[$i] -replace '^\s*\d+\.\s+',''
                [void]$sb.Append((Para '' ((Inline $t)) '<w:ind w:left="420" w:hanging="220"/><w:spacing w:after="30"/>'))
                $i++
            }
            continue
        }
        if ($ln -match '^\s*>\s?') {
            $t = $ln -replace '^\s*>\s?',''
            [void]$sb.Append((Para 'NoteGreen' (Inline $t) ''))
            $i++; continue
        }
        if ($ln -match '^\s*---+\s*$') { $i++; continue }
        if ($ln.Trim() -eq '') { $i++; continue }
        [void]$sb.Append((PlainPara $ln ''))
        $i++
    }
    [void]$sb.Append('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1247" w:header="720" w:footer="720" w:gutter="0"/><w:cols w:space="720"/></w:sectPr>')
    [void]$sb.Append('</w:body></w:document>')
    return $sb.ToString()
}

function StylesXml {
    $x = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    $x += '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    $x += '<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="' + $YAHEI + '" w:eastAsia="' + $YAHEI + '" w:hAnsi="' + $YAHEI + '"/><w:sz w:val="21"/><w:szCs w:val="21"/></w:rPr></w:rPrDefault>'
    $x += '<w:pPrDefault><w:pPr><w:spacing w:after="70" w:line="276" w:lineRule="auto"/><w:jc w:val="both"/></w:pPr></w:pPrDefault></w:docDefaults>'
    $x += '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>'
    $x += '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="300" w:after="140"/><w:outlineLvl w:val="0"/><w:jc w:val="left"/></w:pPr><w:rPr><w:b/><w:color w:val="0B3D91"/><w:sz w:val="30"/><w:szCs w:val="30"/></w:rPr></w:style>'
    $x += '<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="220" w:after="100"/><w:outlineLvl w:val="1"/><w:jc w:val="left"/></w:pPr><w:rPr><w:b/><w:color w:val="123F7A"/><w:sz w:val="25"/><w:szCs w:val="25"/></w:rPr></w:style>'
    $x += '<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="160" w:after="80"/><w:outlineLvl w:val="2"/><w:jc w:val="left"/></w:pPr><w:rPr><w:b/><w:color w:val="1F4E79"/><w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr></w:style>'
    $x += '<w:style w:type="paragraph" w:styleId="Heading4"><w:name w:val="heading 4"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="120" w:after="60"/><w:outlineLvl w:val="3"/><w:jc w:val="left"/></w:pPr><w:rPr><w:b/><w:color w:val="333333"/><w:sz w:val="21"/></w:rPr></w:style>'
    $x += '<w:style w:type="paragraph" w:styleId="Code"><w:name w:val="Code Block"/><w:basedOn w:val="Normal"/><w:qFormat/><w:pPr><w:shd w:val="clear" w:color="auto" w:fill="F4F4F4"/><w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/><w:ind w:left="113" w:right="113"/><w:jc w:val="left"/></w:pPr><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/><w:sz w:val="17"/><w:szCs w:val="17"/></w:rPr></w:style>'
    $x += '<w:style w:type="paragraph" w:styleId="TableText"><w:name w:val="Table Text"/><w:basedOn w:val="Normal"/><w:qFormat/><w:pPr><w:spacing w:before="20" w:after="20" w:line="240" w:lineRule="auto"/><w:jc w:val="left"/></w:pPr><w:rPr><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>'
    $x += '<w:style w:type="paragraph" w:styleId="NoteGreen"><w:name w:val="Note Green"/><w:basedOn w:val="Normal"/><w:qFormat/><w:pPr><w:shd w:val="clear" w:color="auto" w:fill="EEFAF4"/><w:pBdr><w:left w:val="single" w:sz="18" w:space="4" w:color="22AA77"/></w:pBdr><w:spacing w:before="60" w:after="60"/><w:ind w:left="113"/></w:pPr></w:style>'
    $x += '</w:styles>'
    return $x
}

$contentTypes = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>'
$rootRels = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'
$docRels = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>'

function AddEntry($zip, [string]$name, [string]$content) {
    $e = $zip.CreateEntry($name, [IO.Compression.CompressionLevel]::Optimal)
    $s = $e.Open()
    $b = [Text.Encoding]::UTF8.GetBytes($content)
    $s.Write($b, 0, $b.Length)
    $s.Close()
}

$files = Get-ChildItem -Path $Docs -Filter '*.md' -File | Sort-Object Name
$okCount = 0
foreach ($f in $files) {
    $out = Join-Path $f.DirectoryName ($f.BaseName + '.docx')
    $tmp = $out + '.new'
    try {
        if (Test-Path $tmp) { [IO.File]::Delete($tmp) }
        $doc = BuildDocument $f.FullName
        $zip = [IO.Compression.ZipFile]::Open($tmp, [IO.Compression.ZipArchiveMode]::Create)
        AddEntry $zip '[Content_Types].xml' $contentTypes
        AddEntry $zip '_rels/.rels' $rootRels
        AddEntry $zip 'word/_rels/document.xml.rels' $docRels
        AddEntry $zip 'word/styles.xml' (StylesXml)
        AddEntry $zip 'word/document.xml' $doc
        $zip.Dispose()
        Move-Item -LiteralPath $tmp -Destination $out -Force
        Write-Output ('  OK    ' + $f.Name + '  ->  ' + (Split-Path $out -Leaf) + '  (' + [math]::Round((Get-Item $out).Length/1KB,1) + ' KB)')
        $okCount++
    } catch {
        if (Test-Path $tmp) { try { [IO.File]::Delete($tmp) } catch {} }
        $msg = $_.Exception.Message.Split([char]10)[0]
        Write-Output ('  跳过  ' + $f.Name + '  (' + $msg + ')')
    }
}
Write-Output ('成功 ' + $okCount + ' / ' + $files.Count + ' 个，目录: ' + $Docs)
