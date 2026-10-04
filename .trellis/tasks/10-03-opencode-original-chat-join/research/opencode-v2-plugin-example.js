// Install as directory with package.json {"type":"module"}.
// Register absolute directory in user config plugins array.
export default {
  id: "tsunagou.preflight",
  async setup(api) {
    await api.tool.transform((registry) => registry.add({
      name: "tsunagou_probe",
      description: "Report host session identity; accepts no arguments.",
      options: { codemode: false },
      input: { type: "object", properties: {}, additionalProperties: false },
      async execute(_args, context) {
        return { content: [{ type: "text", text: JSON.stringify({ sessionID: context.sessionID }) }] };
      },
    }));
  },
};
