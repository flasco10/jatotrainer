// SPDX-License-Identifier: GPL-3.0-or-later
using System.Text.Json;
using OsuMemoryDataProvider;
using OsuMemoryDataProvider.OsuMemoryModels.Direct;

if (args is ["--self-test"])
{
    Console.WriteLine("Jatotrainer.OsuReader");
    return;
}

using var reader = StructuredOsuMemoryReader.Instance;
var beatmap = new CurrentBeatmap();
// One reader instance retains upstream's signature cache. EOF exits the helper.
while (Console.ReadLine() is not null)
{
    string response = "null";
    try
    {
        if (reader.CanRead && reader.TryRead(beatmap) &&
            !string.IsNullOrWhiteSpace(beatmap.FolderName) &&
            !string.IsNullOrWhiteSpace(beatmap.OsuFileName) &&
            beatmap.OsuFileName.EndsWith(".osu", StringComparison.OrdinalIgnoreCase))
        {
            response = JsonSerializer.Serialize(new {
                folder = beatmap.FolderName, file = beatmap.OsuFileName,
                md5 = beatmap.Md5, bid = beatmap.Id
            });
        }
    }
    catch (Exception ex)
    {
        Console.Error.WriteLine(ex.Message);
    }
    Console.WriteLine(response);
}
